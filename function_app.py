import logging, os, os.path
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp()

def _basename_no_ext(blob_path: str) -> str:
    # works for "container/folder/file.ext" or Windows-style paths
    base = blob_path.replace("\\", "/").split("/")[-1]
    return os.path.splitext(base)[0]

@app.blob_trigger(
    arg_name="inputBlob",
    path="uploads/{name}",               # watches sgdevst01 / uploads
    connection="AzureWebJobsStorage"     # use the Function’s host storage
)
def evidence_extract(inputBlob: func.InputStream):
    logging.info("Blob arrived: %s (%d bytes)", inputBlob.name, inputBlob.length)

    # 1) Analyze with Document Intelligence using Managed Identity
    endpoint = os.environ["DOCINT_ENDPOINT"].rstrip("/")
    cred = DefaultAzureCredential()
    client = DocumentAnalysisClient(endpoint=endpoint, credential=cred)

    # Use prebuilt-read for fast plain text (use "prebuilt-document" for richer output later)
    poller = client.begin_analyze_document("prebuilt-read", inputBlob.read())
    result = poller.result()

    # Flatten text by page → lines
    pages_text = []
    for page in result.pages:
        lines = [line.content for line in page.lines]
        pages_text.append("\n".join(lines))
    text = "\n\n".join(pages_text) or "(no text detected)"

    # 2) Write to evidence/<same-name>.txt in the SAME storage account
    conn = os.environ["AzureWebJobsStorage"]  # connection string injected by the platform
    blob_svc = BlobServiceClient.from_connection_string(conn)
    evidence_container = os.environ.get("EVIDENCE_CONTAINER", "evidence")
    out_name = _basename_no_ext(inputBlob.name) + ".txt"

    blob_svc.get_blob_client(evidence_container, out_name).upload_blob(
        text, overwrite=True
    )
    logging.info("Wrote evidence/%s (%d chars)", out_name, len(text))