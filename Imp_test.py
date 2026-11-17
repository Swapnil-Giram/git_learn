# this is change done by swapnil
# form swapnil branch 

# adding changes for conflict 
import json
import re
import os
import boto3
import creds
from botocore.exceptions import NoCredentialsError
import base64
import requests

from google import genai
from google.genai import types
from json_repair import repair_json

from checklist.Exp_checklist_automation.checklist_schema import SCHEMA

client = genai.Client(api_key=creds.EXPORT_CHECKLIST_API_KEY)
MODEL = "gemini-3.1-pro-preview"

def upload_pdf_to_s3bucket(pdf_file_path, s3_path, product_info, ts, is_template=False):
    
    country = product_info.get('country', 'IN')
    activity = product_info.get('activity', 'EXPORT')
    financial_year = product_info.get('financial_year', '')
    product = product_info.get('product', 'SEA')
    
    bucket_name = creds.S3_BUCKET_NAME
    try :
        s3_client = boto3.client('s3',
                                aws_access_key_id=creds.bl_aws_access_key_id,
                                aws_secret_access_key=creds.bl_aws_secret_access_key,
                                region_name="ap-south-1")
        
        if is_template :
            
            if country == 'ROW' :
                s3_path = f'ROW/{s3_path}'
                
            s3_client.upload_file(pdf_file_path, bucket_name, s3_path)
            print(f"✓ File Uploaded Successfully to s3://{bucket_name}/{s3_path}")
        
        else :
            if s3_path in [f'{product.title()}/{activity.title()}/None_{financial_year}_INV.pdf', f'{product.title()}/{activity.title()}/null_{financial_year}_INV.pdf'] :
                s3_path = f"{product.title()}/{activity.title()}/{ts}_{financial_year}_INV.pdf"
            elif s3_path in [f'{product.title()}/{activity.title()}/None_{financial_year}_CHECKLIST.pdf', f"{product.title()}/{activity.title()}/null_{financial_year}_CHECKLIST.pdf"] :
                s3_path = f"{product.title()}/{activity.title()}/{ts}_{financial_year}_CHECKLIST.pdf" 


            if country == 'ROW' :
                s3_path = f'ROW/{s3_path}'
                
            s3_client.upload_file(pdf_file_path, bucket_name, s3_path)
            print(f"✓ File Uploaded Successfully to s3://{bucket_name}/{s3_path}")

    except FileNotFoundError:
        print(f"The file {pdf_file_path} is not found!")
    except NoCredentialsError:
        print("AWS credential Is Not Configured.")
    except Exception as e :
        print(f"an error occured : {str(e)}")


def process_extracted_json(llm_text: str) -> dict:
    
    # Step 1: Repair and parse JSON
    repaired = repair_json(llm_text)
    data = json.loads(repaired)
    
    # Step 2: Remove empty sections (everything except header and ITEM DETAILS)
    KEEP_ALWAYS = {"header", "ITEM DETAILS"}
    
    def is_empty(value):
        if value is None: return True
        if value == [] or value == {}: return True
        if isinstance(value, list):
            return all(
                all(v in (None, "", [], {}) for v in item.values())
                for item in value if isinstance(item, dict)
            )
        return False
    
    return {
        key: value
        for key, value in data.items()
        if key in KEEP_ALWAYS or not is_empty(value)
    }

# ======================================================================================
def extract_json_safe(llm_text: str) -> dict:
    if not llm_text or not llm_text.strip():
        raise ValueError("Gemini returned EMPTY response")

    # Remove markdown if any
    llm_text = llm_text.replace("```json", "").replace("```", "").strip()

    # Replace Python None/True/False with JSON null/true/false
    llm_text = llm_text.replace("None", "null").replace("True", "true").replace("False", "false") 

    # Try parsing JSON

    try:
        return json.loads(llm_text)
    except json.JSONDecodeError:
        # Try extracting JSON block if extra text exists
        match = re.search(r"\{[\s\S]*\}", llm_text)
        if match: 
            return json.loads(match.group())
    
    raise ValueError("No valid JSON found in Gemini response")




def extract_fields(pdf_path):  
    prompt = f"""
    You are a STRICT JSON extraction engine of Shipping Bill Checklist.

    Rules:
    - ***Output ONLY valid JSON***
    - Extract table columns values carefully and accuratly 
    - Follow the schema EXACTLY
    - Use ONLY keys defined in the schema
    - All repeating sections MUST be JSON arrays
    - NEVER use duplicate keys
    - Don't make mismatch durig extracting the numerical values  
    - Carefully extract accurate numirical value of each fields specially form tabels
    - NEVER use trailing commas
    - IF Consignee Name is not present it has TO Order then use TO Order in Consignee Name  
    - JSON must start with "{" and end with "}"
    - No explanations, no markdown, no comments

    - Dont forgot to give responcen in json followed by schema 
    SPECIAL NOTES:(IMPORTANT)
        In Schema has multiple sections like header , ITEM DETAILS, DEEC DETAILS, DBK DETAILS, ROSCTL DETAILS, 
        PACKING DETAILS, ADDITIONAL DETAILS, SINGLE WINDOW- Additional Product Information,........... and so onn
        multiple times not all sections are present in the pdf so if section is not present in the pdf then does not include section name or anyting about that section in the json output
        only include the sections which are present in the pdf
        and each sections has multiple fields, if section is present and some fields are missing in the pdf then also include those fields with empty string value in the json output.
        - All string values containing newlines must use \\n escape sequence
        - All double quotes inside string values must be escaped as \\"
        - Do not include any unescaped control characters in string values

    - you found EOU IEC number in exporter details 
    TABLE EXTRACTION:
    - Each table row is one separate object in the array
    - Read column headers carefully and match each value to its correct column
    - Do not shift or mix values between columns
    - Extract numbers exactly as shown with all decimals
    - Treat every table as a strict ROW-COLUMN grid: for each row, assign values ONLY to the matching schema field by header meaning and position. NEVER shift values between fields due to line breaks, wrapped text, or missing cells. If a cell is empty, use null and keep all other values in their original columns.
    - Mostly focus on ITEM DETAILS and DBK DETAILS tables for extracting the values accurately

    Schema:
    {json.dumps(SCHEMA, indent=2)}

    extract the fields and info form provided PDF document 

    """
    
    with open(pdf_path, "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=base64.b64decode(pdf_data), mime_type="application/pdf"),
            prompt
        ],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json"
        )
    )

    raw_text = response.text or ""
    print("Finished Export Checklist extraction...")
    try:
        return process_extracted_json(raw_text)
    
    except Exception as e:
        print("\n===== RAW GEMINI OUTPUT START =====\n")
        print(raw_text)
        print("\n===== RAW GEMINI OUTPUT END =====\n")
        raise RuntimeError(f"Gemini JSON parsing failed: {e}")
    
# 38, 40, 58, 60

result = extract_fields(r"D:\python_repo_chk\checklist\ExpData\39-Export CheckList.pdf")
result_json = json.dumps(result, indent=2)
with open("39_exp_chk.json", "w") as f:
    f.write(result_json)
