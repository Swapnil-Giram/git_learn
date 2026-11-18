# now this doing for stashing 
import os
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from json_repair import repair_json
import json
from checklist.Imp_checklist_automation import imp_checklist_schema
import creds
from checklist.Exp_checklist_automation.checklist_schema import SCHEMA


MODEL = "global.anthropic.claude-haiku-5-5"                    
BEDROCK_REGION ="ap-south-1"
MAX_OUTPUT_TOKENS = 16000

# Max document size
MAX_PDF_BYTES = 4_500_000

# Price per 1M tokens
PRICE_PER_M_INPUT = 0.10
PRICE_PER_M_OUTPUT = 0.50


_BOTO_CONFIG = Config(
    retries={"max_attempts": 2, "mode": "adaptive"},
    read_timeout=100,   )


def _bedrock_client():
    return boto3.client(
        "bedrock-runtime",
        aws_access_key_id=creds.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=creds.AWS_SECRET_ACCESS_KEY,
        region_name=BEDROCK_REGION,
        config=_BOTO_CONFIG,)

def process_extracted_json(llm_text: str) -> dict:
    repaired = repair_json(llm_text)
    data = json.loads(repaired)
    # Remove empty sections (everything except header and ITEM DETAILS)
    KEEP_ALWAYS = {"header", "ITEM DETAILS"}
    def is_empty(value):
        if value is None: return True
        if value == [] or value == {}: return True
        if isinstance(value, list):
            return all(
                all(v in (None, "", [], {}) for v in item.values())
                for item in value if isinstance(item, dict))
        return False
    return {
        key: value
        for key, value in data.items()
        if key in KEEP_ALWAYS or not is_empty(value)}


SYSTEM_PROMPT = (
    "You are a STRICT JSON extraction engine for Shipping Bill Checklists. "
    "Read the attached PDF and extract its content into the given schema. "
    "Use ONLY information present in the document; never invent values.")


def build_prompt() -> str:
    return f"""
    Rules:
    - Output ONLY valid JSON, starting with "{{" and ending with "}}". No explanations, no markdown, no comments.
    - Follow the schema EXACTLY and use ONLY keys defined in the schema.
    - All repeating sections MUST be JSON arrays. NEVER use duplicate keys or trailing commas.
    - If Consignee Name is not present and "TO Order" appears, use "TO Order" as the Consignee Name.
    - You will find the EOU IEC number in the exporter details.
    - The schema has multiple sections (header, ITEM DETAILS, DEEC DETAILS, DBK DETAILS, ROSCTL DETAILS,
    PACKING DETAILS, ADDITIONAL DETAILS, SINGLE WINDOW - Additional Product Information, and so on).
    Not every section is present in every PDF. If a section is NOT present, omit it completely
    (no section name, nothing about it). If a section IS present but some fields are missing,
    include those fields with an empty string.

    TABLE EXTRACTION:
    - Each table row is one separate object in the array.
    - Treat every table as a strict ROW-COLUMN grid: read the column headers carefully and assign each value
        ONLY to the matching schema field by header meaning and position. NEVER shift or mix values between
        columns because of line breaks, wrapped text or missing cells. If a cell is empty, use null and keep
        all other values in their original columns.
    - Copy numbers exactly as shown, with all decimals. Do not mismatch numerical values.
    - Pay the most attention to the ITEM DETAILS and DBK DETAILS tables.

    Schema:
    {json.dumps(SCHEMA, indent=2)}

    Extract the fields from the attached PDF document and return JSON in exactly this schema.
    """

def extract_fields(pdf_path):
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
                    {"document": {"format": "pdf", "name": "checklist",
                                  "source": {"bytes": pdf_bytes}}},
                    {"text": build_prompt()},],
                    }],
            inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS},)#, "temperature": 0},)
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"Bedrock call failed: {e}")
    
    usage = response.get("usage", {}) or {}
    in_tok = usage.get("inputTokens", 0)
    out_tok = usage.get("outputTokens", 0)
    cost = in_tok / 1e6 * PRICE_PER_M_INPUT + out_tok / 1e6 * PRICE_PER_M_OUTPUT
    print(f"[Bedrock usage - EXPORT Checklist] {os.path.basename(pdf_path)} | model={MODEL} | "
          f"input={in_tok} output={out_tok} | est. cost=${cost:.5f} | "
          f"latency={(response.get('metrics') or {}).get('latencyMs')}ms")
    
    raw_text = "".join(
        part.get("text", "") for part in response["output"]["message"]["content"])

    if response.get("stopReason") == "max_tokens":
        print("\n===== RAW LLM OUTPUT (TRUNCATED) =====\n")
        print(raw_text)
        raise RuntimeError(
            f"Model output hit the {MAX_OUTPUT_TOKENS}-token limit and was cut off. ")

    print("Finished Export Checklist extraction...")
    try:
        return process_extracted_json(raw_text)

    except Exception as e:
        print("\n===== RAW LLM OUTPUT START =====\n")
        print(raw_text)
        print("\n===== RAW LLM OUTPUT END =====\n")
        raise RuntimeError(f"LLM JSON parsing failed: {e}")


result = extract_fields(r"checklist/ExpData/Export CheckList-HY IMKO58.pdf")
result_json = json.dumps(result, indent=2)
with open("58_exp_chk.json", "w") as f:
    f.write(result_json)


# ==========================================================================================================




# import json
# import os
# import boto3
# from botocore.config import Config
# from botocore.exceptions import BotoCoreError, ClientError
# from json_repair import repair_json
# import creds
# from checklist.Imp_checklist_automation.imp_checklist_schema import SCHEMA

# MODEL = "global.anthropic.claude-haiku-5-5"                    
# BEDROCK_REGION =  "ap-south-1"
# MAX_OUTPUT_TOKENS = 20000

# # Max document size
# MAX_PDF_BYTES = 4_500_000

# # Price per 1M tokens
# PRICE_PER_M_INPUT = 0.10
# PRICE_PER_M_OUTPUT =  0.50

# BOTO_CONFIG = Config(
#     retries={"max_attempts": 2, "mode": "adaptive"},
#     read_timeout=100,)
# # 00 (Free Shipping bill involving remittance of Foreign exchange)
# # 00 (Free Shipping bill involving remitttance of Foreign exchange)

# def _bedrock_client():
#     return boto3.client(
#         "bedrock-runtime",
#         aws_access_key_id=creds.AWS_ACCESS_KEY_ID,
#         aws_secret_access_key=creds.AWS_SECRET_ACCESS_KEY,
#         region_name=BEDROCK_REGION,
#         config=BOTO_CONFIG,)


# def process_extracted_json(llm_text: str) -> dict:
#     repaired = repair_json(llm_text)
#     data = json.loads(repaired)

#     # Remove empty sections (everything except header and ITEM DETAILS)
#     KEEP_ALWAYS = {"header", "ITEM DETAILS"}
#     def is_empty(value):
#         if value is None: return True
#         if value == [] or value == {}: return True
#         if isinstance(value, list):
#             return all(
#                 all(v in (None, "", [], {}) for v in item.values())
#                 for item in value if isinstance(item, dict))
#         return False
#     return {
#         key: value
#         for key, value in data.items()
#         if key in KEEP_ALWAYS or not is_empty(value)}


# # Prompt
# SYSTEM_PROMPT = (
#     "You are a STRICT JSON extraction engine for Import Bill Checklists. "
#     "Read the attached PDF and extract its content into the given schema. "
#     "Use ONLY information present in the document; never invent values.")


# def build_prompt():
#     return f"""
#     Rules:
#     - Output ONLY valid JSON, starting with "{{" and ending with "}}". No explanations, no markdown, no comment6s.
#     - Follow the schema EXACTLY and use ONLY keys defined in the schema.
#     - If a section or dictionary from the schema is missing in the document, do not add anything about it:
#     - do not even add that key or section header to the JSON output.
#     - All repeating sections MUST be JSON arrays. NEVER use duplicate keys or trailing commas.
#     - Do not mismatch numerical values; extract the numbers of every field accurately, especially from tables.
#     - **Extract CHA, Importers, Consignee, Buyers, Exporter and Shipper details from the document carefully. If a field is missing, use an empty string.**
#     - CHA GSTIN 14-digit/char number present in CHA Details section extract carefully and map it. 
#     - Some sections has sometimes multiple Items so extract all of them.

#     **TABLE EXTRACTION:**
#     - Each table row is one separate object in the array.
#     - Treat every table as a strict ROW-COLUMN grid: read the column headers carefully and assign each value
#       ONLY to the matching schema field by header meaning and position. NEVER shift or mix values between
#       columns because of line breaks, wrapped text or missing cells. If a cell is empty, use null and keep
#       all other values in their original columns and map it correctly.
#     - Copy numbers exactly as shown, with all decimals.
#     - **Mostly focus on Item Details table table its row-column values is critiacl to extract accurately.**

#     Schema:
#     {json.dumps(SCHEMA, indent=2)}
#     Extract the fields from the attached PDF document and return JSON in exactly this schema.
#     """    

# def extract_fields_imp_chk(pdf_path):
#     print("Started Import Checklist extraction...")

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
#                     {"document": {"format": "pdf", "name": "checklist",
#                                   "source": {"bytes": pdf_bytes}}},
#                     {"text": build_prompt()},
#                 ],
#             }],
#             inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS,},
#             additionalModelRequestFields={"thinking": {"type": "adaptive"}},
#             outputConfig={
#             "effort": "medium"},)# "temperature": 0.2},)
#     except (ClientError, BotoCoreError) as e:
#         raise RuntimeError(f"Bedrock call failed: {e}")

#     usage = response.get("usage", {}) or {}
#     in_tok = usage.get("inputTokens", 0)
#     out_tok = usage.get("outputTokens", 0)
#     cost = in_tok / 1e6 * PRICE_PER_M_INPUT + out_tok / 1e6 * PRICE_PER_M_OUTPUT
#     print(f"[Bedrock usage - IMPORT checklist] {os.path.basename(pdf_path)} | model={MODEL} | "
#           f"input={in_tok} output={out_tok} | est. cost=${cost:.5f} | "
#           f"latency={(response.get('metrics') or {}).get('latencyMs')}ms")
    
#     raw_text = "".join(part.get("text", "") for part in response["output"]["message"]["content"])

#     if response.get("stopReason") == "max_tokens":
#         print("\n===== RAW LLM OUTPUT (TRUNCATED) =====\n")
#         print(raw_text)
#         raise RuntimeError(
#             f"Model output hit the {MAX_OUTPUT_TOKENS}-token limit and was cut off. ")

#     print("Finished Import Checklist extraction...")
#     try:
#         return process_extracted_json(raw_text)

#     except Exception as e:
#         print("\n===== RAW LLM OUTPUT START =====\n")
#         print(raw_text)
#         print("\n===== RAW LLM OUTPUT END =====\n")
#         raise RuntimeError(f"LLM JSON parsing failed: {e}")



# result = extract_fields_imp_chk(r"D:\python_repo_chk\checklist\ImpData\YASH CHECKLIST.pdf")
# result_json = json.dumps(result, indent=2)
# with open("imp_chk_yash.json", "w") as f:
#     f.write(result_json)
