
import json
import os

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from json_repair import repair_json

# from checklist.Exp_checklist_automation import invoice_schema
import creds
from checklist.Exp_checklist_automation.invoice_schema import SCHEMA

# Configuration
BEDROCK_REGION = "ap-south-1"
MAX_OUTPUT_TOKENS = 10000

# Bedrock Converse accepts at most ~4.5 MB per document.
MAX_PDF_BYTES = 4_500_000

MODEL = "global.anthropic.claude-haiku-5-5"
PRICE_PER_M_INPUT = 0.10
PRICE_PER_M_OUTPUT = 0.50

_BOTO_CONFIG = Config(
    retries={"max_attempts": 2, "mode": "adaptive"},
    read_timeout=40,)


def _bedrock_client():
    return boto3.client(
        "bedrock-runtime",
        aws_access_key_id=creds.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=creds.AWS_SECRET_ACCESS_KEY,
        region_name=BEDROCK_REGION,
        config=_BOTO_CONFIG,)


# Prompt
SYSTEM_PROMPT = (
    "You are an expert at extracting structured data from export invoices. "
    "Read the attached PDF and extract its content into the given schema. "
    "Use ONLY information present in the document; never invent values.")

prompt = f"""You are an expert at extracting structured data from export invoices.
    TASK: Extract data from the provided export invoice with complete accuracy.
    Sometimes the quality of the image may be poor, but you must extract the data as accurately as possible.
    CRITICAL INSTRUCTIONS:
    1. Read the schema carefully before extraction and extract only the fields mentioned in the schema and fill their values smartly.
    2. Map values to their correct fields only - do not confuse similar fields
    3. Understand the context and meaning of each field before mapping
    4. Never guess or assume field values - only extract what is clearly present
    5. Remember this is an EXPORT invoice - interpret all fields accordingly
    6. If a field is not found in the invoice, leave it empty in the output
    7. Do not add any fields not present in the schema
    8. Do not use any markdown formatting in your response
    9. Ensure the output is valid JSON matching the schema exactly
    10. Copy numbers exactly as shown, with all decimals

    SCHEMA:
    {json.dumps(SCHEMA, indent=2)}

    OUTPUT REQUIREMENTS:
    - Return ONLY valid JSON matching the schema exactly
    - The JSON must start with "{{" and end with "}}"
    - Include all fields defined in the schema
    - Use empty strings or null for missing values
    - Ensure proper JSON formatting
    """


def _parse_json(raw_text: str):
    """Parse model output; tolerate markdown fences or small JSON glitches."""
    cleaned = raw_text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return json.loads(repair_json(cleaned))


def extract_invoice_fields(pdf_path):
    print("started Export Invoice extraction")
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    if not pdf_bytes:
        raise ValueError(f"PDF is empty: {pdf_path}")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError(
            f"PDF is {len(pdf_bytes) / 1e6:.1f} MB; max is"
            f"{MAX_PDF_BYTES / 1e6:.1f} MB per document. Compress the PDF first.")
    try:
        response = _bedrock_client().converse(
            modelId=MODEL,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{
                "role": "user",
                "content": [
                    {"document": {"format": "pdf", "name": "invoice",
                                  "source": {"bytes": pdf_bytes}}},
                    {"text": prompt},],}],
            inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS},)#, "temperature": 0},)

    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"Bedrock call failed: {e}")

    usage = response.get("usage", {}) or {}
    in_tok = usage.get("inputTokens", 0)
    out_tok = usage.get("outputTokens", 0)
    cost = in_tok / 1e6 * PRICE_PER_M_INPUT + out_tok / 1e6 * PRICE_PER_M_OUTPUT
    print(f"[Bedrock usage - EXPORT invoice] {os.path.basename(pdf_path)} | model={MODEL} | "
          f"input={in_tok} output={out_tok} | est. cost=${cost:.5f} | "
          f"latency={(response.get('metrics') or {}).get('latencyMs')}ms")

    raw_text = "".join(part.get("text", "") for part in response["output"]["message"]["content"])

    if response.get("stopReason") == "max_tokens":
        print("\n===== RAW LLM OUTPUT (TRUNCATED) =====\n")
        print(raw_text)
        raise RuntimeError(
            f"Model output hit the {MAX_OUTPUT_TOKENS}-token limit and was cut off. ")

    print("Finished Export Invoice extraction...")
    try:
        return _parse_json(raw_text)
    except Exception as e:
        print("\n===== RAW LLM OUTPUT START =====\n")
        print(raw_text)
        print("\n===== RAW LLM OUTPUT END =====\n")
        raise RuntimeError(f"LLM JSON parsing failed: {e}") 


result = extract_invoice_fields(r"D:\python_repo_chk\checklist\ExpData\38_exp_inv.pdf")
result_json = json.dumps(result, indent=2)
with open("38_exp_inv.json", "w") as f:
    f.write(result_json)









# import json
# import os
# import boto3
# from botocore.config import Config
# from botocore.exceptions import BotoCoreError, ClientError
# from json_repair import repair_json

# import creds
# from .imp_invoice_schema import SCHEMA

# MODEL = "global.anthropic.claude-haiku-5-5"                     
# BEDROCK_REGION = "ap-south-1"
# MAX_OUTPUT_TOKENS = 8000

# # Bedrock Converse accepts at most ~4.5 MB per document.
# MAX_PDF_BYTES = 4_500_000

# # Price per 1M tokens, for model  "global.amazon.nova-2-lite-v1:0" (Bedrock Converse)
# PRICE_PER_M_INPUT = 0.10
# PRICE_PER_M_OUTPUT = 0.50

# BOTO_CONFIG = Config(
#     retries={"max_attempts": 2, "mode": "adaptive"},
#     read_timeout= 40,)

# def _bedrock_client():
#     return boto3.client(
#         "bedrock-runtime",
#         aws_access_key_id=creds.Bedrock_aws_access_key_id,
#         aws_secret_access_key=creds.Bedrock_aws_secret_access_key,
#         region_name=BEDROCK_REGION,
#         config=BOTO_CONFIG,)


# # Prompt
# SYSTEM_PROMPT = (
#     "You are a STRICT JSON extraction engine for import invoices. "
#     "Read the attached PDF and extract its content into the given schema. "
#     "Use ONLY information present in the document; never invent values.")

# prompt = f"""Extract data from this import invoice. Focus on accuracy.

#     FIND THESE FIELDS:
#     - Invoice number and date (top of document)
#     - Exporter: company name, address, IEC code
#     - and Buyer details
#     - Ports: loading and discharge
#     - Destination country
#     - Currency and total amount
#     - Payment terms
#     - Items table: for EACH row extract description, quantity, unit, unit price, amount, HS code
#     - Only extract the english language text from the document. Ignore any other language text.
#     - **Extract CHA, Importers, Consignee, Buyers, Exporter and Shipper details from the document carefully. If a field is missing, use an empty string.**
#     - **Some fields keys-values may not present in the document but values is present in the document, in that case extract the value and map it to the correct field key in the schema by thinking. But dont map any irrelevant value to the field key.**


#     Return ONLY valid JSON (no markdown, no explanations, no comments):
#     - The JSON must start with "{{" and end with "}}".
#     - Follow the schema EXACTLY.
#     - Use ONLY keys defined in the schema.
#     - Copy numbers exactly as shown, with all decimals.
#     - If a value is not present in the document, use an empty string.

#     Schema:
#     {json.dumps(SCHEMA, indent=2)}
#     Extract the fields from the attached PDF document and return JSON in exactly this schema.
#     """


# def _parse_json(raw_text: str):
#     """Parse model output; tolerate markdown fences or small JSON glitches."""
#     cleaned = raw_text.strip().replace("```json", "").replace("```", "").strip()
#     try:
#         return json.loads(cleaned)
#     except json.JSONDecodeError:
#         return json.loads(repair_json(cleaned))


# def extract_imp_invoice_fields(pdf_path):
#     print("started Import Invoice extraction")
#     with open(pdf_path, "rb") as f:
#         pdf_bytes = f.read()

#     if not pdf_bytes:
#         raise ValueError(f"PDF is empty: {pdf_path}")
#     if len(pdf_bytes) > MAX_PDF_BYTES:
#         raise ValueError(
#             f"PDF is {len(pdf_bytes) / 1e6:.1f} MB; max is"
#             f"{MAX_PDF_BYTES / 1e6:.1f} MB per document. Compress the PDF first.")
#     try:
#         response = _bedrock_client().converse(
#             modelId=MODEL,
#             system=[{"text": SYSTEM_PROMPT}],
#             messages=[{
#                 "role": "user",
#                 "content": [
#                     {"document": {"format": "pdf", "name": "invoice",
#                                   "source": {"bytes": pdf_bytes}}},
#                     {"text": prompt},
#                 ],
#             }],
#             inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS},)
        
#     except (ClientError, BotoCoreError) as e:
#         raise RuntimeError(f"Bedrock call failed: {e}")

#     usage = response.get("usage", {}) or {}
#     in_tok = usage.get("inputTokens", 0)
#     out_tok = usage.get("outputTokens", 0)
#     cost = in_tok / 1e6 * PRICE_PER_M_INPUT + out_tok / 1e6 * PRICE_PER_M_OUTPUT
#     print(f"[Bedrock usage - IMPORT invoice] {os.path.basename(pdf_path)} | model={MODEL} | "
#           f"input={in_tok} output={out_tok} | est. cost=${cost:.5f} | "
#           f"latency={(response.get('metrics') or {}).get('latencyMs')}ms")

#     raw_text = "".join(part.get("text", "") for part in response["output"]["message"]["content"])

#     if response.get("stopReason") == "max_tokens":
#         print("\n===== RAW LLM OUTPUT (TRUNCATED) =====\n")
#         print(raw_text)
#         raise RuntimeError(
#             f"Model output hit the {MAX_OUTPUT_TOKENS}-token limit and was cut off. ")

#     print("Finished Import Invoice extraction...")
#     try:
#         return _parse_json(raw_text)
#     except Exception as e:
#         print("\n===== RAW LLM OUTPUT START =====\n")
#         print(raw_text)
#         print("\n===== RAW LLM OUTPUT END =====\n")
#         raise RuntimeError(f"LLM JSON parsing failed: {e}")


# # result = extract_imp_invoice_fields(r"d:\cheklist\a_imp\data\YASH invoice.pdf")

# # result_json = json.dumps(result, indent=2)

# # with open("Import_invoice_result.json", "w") as f:
# #     f.write(result_json)