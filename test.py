"""
File with all API defined for pythonAPI server
"""
import datetime
import os
import traceback
import geopy
import geopy.distance
import uvicorn
import boto3

from typing import Optional
from chatbot.chat import app as chatbotapi
from chatbot.index_schema import index_alldocs
from downloadapi.download import app as smartreport
from fastapi.staticfiles import StaticFiles
import creds
from databaseConnectivity.queries import *
from dateutil.tz import gettz
from fastapi import FastAPI, status, File, BackgroundTasks, Form
from fastapi.logger import logger as fastapi_logger
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from geographiclib.geodesic import Geodesic
# from getS3Image.getimage import getimage
from liveStream.streaming_video import main
from pydantic import BaseModel
from pytz import timezone
from sendcontainermail.sendcontainermail import sendcontainermail
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from PIL import Image
import numpy as np
from io import BytesIO
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.concurrency import run_in_threadpool
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from PyPDF2 import PdfReader,PdfWriter
from botocore.exceptions import ClientError
import io
import pandas as pd
import shutil
from pathlib import Path
import time
import warnings
import logging
import asyncio
from HSN_Exim_Details.main import app as EximDetails
from container_ocr.main import app as Container_info
from vehicle_num_ocr.main import app as Vehicle_info
from lolo_do_booking.main import app as lolo_do
from shipping_bill_ocr.main import app as shipping_bill

from eaudit_BL.api.routes import app as bl_extraction_app
from eaudit_BL.sqllite import _ensure_table, get_db_path
from create_si.main import app as create_mbl
from create_si.data_storage.sqlite import create_mbl_table
from Exp_checklist_automation.sql3DB import create_checklist_automation_table
from checklist.api import app as checklist_app        

LOG_FILE = "app.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

url = creds.domainname



app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/chatbot", chatbotapi)
app.mount("/downloadapi", smartreport)
app.mount("/eximDetails", EximDetails)
app.mount("/containerInfo", Container_info)
app.mount("/vehicleInfo",Vehicle_info)
app.mount("/lolodetails",lolo_do)
app.mount("/shippingBill", shipping_bill)
app.mount("/eauditBL", bl_extraction_app)
app.mount("/mbl", create_mbl)
app.mount("/checklist", checklist_app)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.get('/')
def welcome():
    return "Welcome to matrixapi"


################################ LOGS ########################################
log_folder = './'
if not os.path.isdir(os.path.join(log_folder, 'logs')):
    os.makedirs(os.path.join(log_folder, 'logs'))


tz = timezone('Asia/Kolkata')
def timetz(*args):
    """
    Convert timezone to IST for logging
    """
    return datetime.datetime.now(tz).timetuple()


############################ shipping line vs cfs MAP API #########################
@app.get('/shippinglinevscfs_count')
async def shipping_line_vsCFS(request: Request, sl_name=None, cfs_name=None, port=None, container_type=None, load_type=None):
    try:
        header = request.headers
        # print("headers:",header)
        if "api_key" not in header or "secret_key" not in header:
            return PlainTextResponse(
                "Direct access to the API not allowed.", status_code=status.HTTP_403_FORBIDDEN
            )
        elif header["api_key"] != creds.api_key or header["secret_key"] != creds.secret_key:
            return PlainTextResponse(
                "Unauthorized access.", status_code=status.HTTP_401_UNAUTHORIZED
            )

        tabular, total = run_query_shippingline_vs_cfs(
            sl_name, cfs_name, port, container_type, load_type)
        total = total[0][0]

        if len(tabular) == 0:
            return "Record Not Found"

        counter = {}

        for item in tabular:
            item = list(item)

            if item[1] == None:
                item[1] = 'other'

            if item[0] not in counter:
                counter[item[0]] = [{
                    'CFS_Name': item[1] if item[1] is not None else 'other',
                    'count': [item[2] if item[2] is not None else 'other'],
                    'counting': [item[3]]
                }]
            else:
                present = False
                for sl in counter[item[0]]:

                    if sl['CFS_Name'] == item[1]:
                        sl['count'].append(
                            item[2] if item[2] is not None else 'other')
                        sl['counting'].append(item[3])
                        present = True

                if present == False:
                    counter[item[0]].append({
                        'CFS_Name': item[1] if item[1] is not None else 'other',
                        'count': [item[2] if item[2] is not None else 'other'],
                        'counting': [item[3]]
                    })

        for key in counter.keys():
            for val in counter[key]:
                count_type = {
                    '20ft': 0,
                    '40ft': 0,
                    '45ft': 0,
                    'invalid': 0
                }

                for count, freq in zip(val['count'], val['counting']):
                    if '20' in count:
                        count_type['20ft'] += freq
                    elif '40' in count:
                        count_type['40ft'] += freq
                    elif '45' in count:
                        count_type['45ft'] += freq
                    elif 'other' in count:
                        count_type['invalid'] += freq

                count_type['total'] = count_type['20ft'] + \
                    count_type['40ft'] + count_type['45ft'] + \
                    count_type['invalid']

                val['count'] = count_type

                del val['counting']

        return {
            'counterList': counter,
            'total_containers': total,
            'response_status_code': 200
        }
    except Exception as e:
        print(f'[ALERT] Error caused by {e}')
        # update_log_file(e)
        return e


############################ Origin & Destination Count #########################
@app.get('/origindestination_count')
async def origin_destination_matrix(request: Request, load_type=None, con_lr_no=None, con_type=None, transporter=None):
    try:
        header = request.headers
        if "api_key" not in header or "secret_key" not in header:
            return PlainTextResponse(
                "Direct access to the API not allowed.", status_code=status.HTTP_403_FORBIDDEN
            )
        elif header["api_key"] != creds.api_key or header["secret_key"] !=creds.secret_key:
            return PlainTextResponse(
                "Unauthorized access.", status_code=status.HTTP_401_UNAUTHORIZED
            )

        query = run_query_origin_destination_count(
            load_type, con_lr_no, con_type, transporter)
        if len(query) == 0:
            return "Record Not Found"

        # making response format
        res = {}
        for item in query:
            item = list(item)
            if item[0] not in res:
                res['source'] = item[0]
                res['countlist'] = [{
                    'destination': item[1] if item[1] is not None else 'Invalid',
                    'count': [item[2] if item[2] is not None else 'Invalid'],
                    'counting': [item[3]]
                }]
            else:
                present = False
                for src in res[item[0]]:
                    if src['destination'] == item[1]:
                        src['count'].append(
                            item[2] if item[2] is not None else 'Invalid')
                        src['counting'].append(item[3])
                    present = True

                if present == False:
                    res[item[0]].append({
                        'destination': item[1] if item[1] is not None else 'Invalid',
                        'count': [item[2] if item[2] is not None else 'Invalid'],
                        'counting': [item[3]]
                    })

        for i in res['countlist']:
            count_type = {
                'twentyft': 0,
                'fortyft': 0,
                'fortyfiveft': 0,
                'twentyft_refer': 0,
                'fortyft_refer': 0,
                'invalid': 0
            }

            for count, freq in zip(i['count'], i['counting']):
                if '20' in count:
                    count_type['twentyft'] += freq
                elif '40' in count:
                    count_type['fortyft'] += freq
                elif '45' in count:
                    count_type['fortyfiveft'] += freq
                elif '20' and 'REFER' in count:
                    count_type['twentyft_refer'] += freq
                elif '40' and 'REFER' in count:
                    count_type['fortyft_refer'] += freq
                elif 'Invalid' in count:
                    count_type['invalid'] += freq
                                    
            count_type['total'] = count_type['twentyft'] + count_type['fortyft'] + count_type['fortyfiveft'] + \
                count_type['twentyft_refer'] + \
                count_type['fortyft_refer'] + count_type['invalid']

            i['count'] = count_type

            del i['counting']
        return {"originDestinationCountMap": [res],
                'response_status_code': 200
                }
    except Exception as e:
        print(f'[ALERT] Error caused by {e}')
        # update_log_file(e)
        return e


############################ Error Email Send #########################
class EmailContents(BaseModel):
    containerId: int
    ToEmail: str


# @app.put("/sendemail")
# def sendemail(email_contents: EmailContents):
#     try:
#         IST = gettz("Asia/Kolkata")
#         now = datetime.datetime.now(tz=IST)
#         dt_string = now.strftime("%d/%m/%Y %H:%M %p")
#         res = get_container_images(email_contents.containerId)
#         assert (len(
#             res) != 0), f"Found no records for container id {email_contents.containerId} in the database"

#         fromemail = str(res[0][12] or "")
#         toemail = str(email_contents.ToEmail or "")
#         container_number = str(res[0][1] or "")
#         sitename = str(res[0][5] or "")
#         siteaddress = str(res[0][6] or "")
#         shippingline = str(res[0][7] or "")
#         containertype = str(res[0][8] or "")
#         jobid = str(res[0][9] or "")
#         igmno = str(res[0][10] or "")
#         inwarddate = str(res[0][11] or "")

#         images_path = getimage(aws_keys, res)
#         emailtext = f"""
#                     <html lang="en">
#                         <body style="margin:0; padding:0; background-color:#fff;">
#                            <p>Dear Customer,<br>
#                             <br>
#                             Kindly find attached herewith the <b>"Container Images Report”</b> for {sitename} generated on {dt_string}
#                             <br>
#                             <br>Thanking you<br>
#                             Team conmove<br>
#                             <a href="http://www.conmove.io/">www.conmove.io</a>
#                             </p>
#                         </body>
#                     </html>

#         """
#         print(images_path)
#         sendcontainermail(emailtext, images_path, email_contents, container_number, fromemail,
#                           toemail, sitename, siteaddress, shippingline, containertype, jobid, igmno, inwarddate)
        
#         return {
#             "status": "success",
#             "message": "Mail Sent"
#         }
#     except Exception as e:
#         print(str(e))
#         # update_log_file(e)
#         fastapi_logger.error(
#             f"""
#             Error:{''.join(traceback.TracebackException.from_exception(e).format())}
#             """)
#         return {
#             "status": "failed",
#             'message': str(e)
#         }

############################ Boxgate Live Straming #########################
@app.get('/stream')
def stream(CamIp, cfsip, CamType, detection=True):
    return StreamingResponse(main(CamIp, cfsip, CamType, False), media_type="multipart/x-mixed-replace;boundary=frame")


############################ Make CFS Yard #########################
class OriginCordinates(BaseModel):
    latitude: float
    longitude: float


def get_new_cordinate(lat, lon, bearing, distance_ft):
    start_point = geopy.Point(lat, lon)
    end_point = geopy.distance.geodesic(
        feet=distance_ft).destination(start_point, bearing)
    return (end_point.latitude, end_point.longitude)


@app.get('/makecfsyard')
def makecfsyard(columns, rows, og_lat, og_lon, og_lat2, og_lon2, zoneType = 0):
    try:
        zoneType = int(zoneType)
        lat_lis = []
        lon_lis = []
        bearing_dict = Geodesic.WGS84.Inverse(
            float(og_lat), float(og_lon), float(og_lat2), float(og_lon2))
        BEARING = bearing_dict['azi2']
        lat_lis.append(og_lat)
        lon_lis.append(og_lon)
        # Container
        if zoneType == 0:
            for row in range(1, int(rows)+1):
                if row == 1:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 7)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords
                elif row % 2 == 0:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 20)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords
                else:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 27)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords

                for col in range(1, int(columns)+1):
                    if col == 1:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 4)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
                    else:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 7.5)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
            return {
                'lat': lat_lis,
                'lon': lon_lis,
                'bearing': BEARING
            }
        
        # Ingot
        elif zoneType == 1:
            for row in range(1, int(rows)+1):
                if row == 1:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 1.25)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords
                elif (row-1)%3 == 0:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 3.5)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords
                else:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 2.5)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords

                for col in range(1, int(columns)+1):
                    if col == 1:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 1.25)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
                    else:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 2.5)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
            return {
                'lat': lat_lis,
                'lon': lon_lis,
                'bearing': BEARING
            }
        
        # Cast Bar
        elif zoneType == 2:
            for row in range(1, int(rows)+1):
                if row == 1:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 1.25)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords
                elif (row-1)%3 == 0:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 3.5)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords
                else:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 2.5)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords

                for col in range(1, int(columns)+1):
                    if col == 1:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 1.25)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
                    else:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 2.5)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
            return {
                'lat': lat_lis,
                'lon': lon_lis,
                'bearing': BEARING
            }
        
        # Sow Ingot
        elif zoneType == 3:
            for row in range(1, int(rows)+1):
                if row == 1:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 2.5)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords
                else:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 6)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords

                for col in range(1, int(columns)+1):
                    if col == 1:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 1.75)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
                    else:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 4.5)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
            return {
                'lat': lat_lis,
                'lon': lon_lis,
                'bearing': BEARING
            }
        
        # Billet
        elif zoneType == 4:
            for row in range(1, int(rows)+1):
                if row == 1:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 1.75)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords
                else:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 4.5)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords

                for col in range(1, int(columns)+1):
                    if col == 1:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 7)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
                    else:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 22)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
            return {
                'lat': lat_lis,
                'lon': lon_lis,
                'bearing': BEARING
            }
        
        # Wire Rod
        elif zoneType==5:
            for row in range(1, int(rows)+1):
                if row==1:
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 2.5)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords
                else :
                    new_cords = get_new_cordinate(og_lat, og_lon, BEARING, 5)
                    lat, lon = new_cords
                    og_lat, og_lon = new_cords
                for col in range(1, int(columns)+1):
                    if col == 1:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 2.5)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
                    else:
                        new_cords = get_new_cordinate(lat, lon, 90+BEARING, 6.3)
                        lat, lon = new_cords
                        lat_lis.append(lat)
                        lon_lis.append(lon)
            return {
                'lat': lat_lis,
                'lon': lon_lis,
                'bearing': BEARING
            }

    except Exception as e:
        return {
            'status': 'failed',
            'message': str(e)
        }


######################### Driving Licence Data Extraction #####################
from driving_licence import get_licence_ocr
@app.put("/licencedetails")
def getLicenceDetails(file: bytes = File()):
    try:
        numpy_array = np.array(Image.open(BytesIO(file)))
        data=get_licence_ocr(numpy_array)
        fastapi_logger.info(
            f"""
            API:licencedetails |
            data: {data} |
            """)
        return data
        
    except Exception as e:
        fastapi_logger.error(
            f"""
            Error:{''.join(traceback.TracebackException.from_exception(e).format())}
            """)
        return {
            'status': 'failed',
            'message': str(e)
        }


######################### Export Invoice & Packing List ###########################
from invoiceandpacking import get_ocr_export_invoice
@app.put("/invoiceocr")
def getShippingInvoice_ocr(file: UploadFile):
    try:
        if file.content_type=="application/pdf": 
            image_bytes=file.file.read()
            image_bytes=bytearray(image_bytes)
            # for calculate len of pdf
            pdf_stream = io.BytesIO(image_bytes)
            pdf_reader = PdfReader(pdf_stream)

            output_list = []
            for i in range(len(pdf_reader.pages)):
                pdf_writer = PdfWriter()
                pdf_writer.add_page(pdf_reader.pages[i])
                output_stream = io.BytesIO()
                pdf_writer.write(output_stream)
                image_bytes = output_stream.getvalue()
                data = get_ocr_export_invoice(image_bytes)
                output_list.append(data)             
            
            result =output_list[0]
            for i in range(len(output_list)-1):
                output = {}
                for key, value in result.items():
                    if key not in output or (value != '' and output[key] == ''):
                        output[key] = value
                for key, value in output_list[i+1].items():
                    if key not in output or (value != '' and output[key] == ''):
                        output[key] = value
                result.update(output)
            
            return result

    except Exception as e:
        print(e)
        return f'error : {e}'


################################### POWERBI #######################################
def send_email(user_id, product, user_type):
    sender_email = creds.intel_email
    receiver_email = creds.bl_receiver_mails
    password = creds.intel_password

    message = MIMEMultipart("alternative")
    message["Subject"] = "Local URL Not Found"
    message["From"] = sender_email
    message["To"] = ", ".join(receiver_email)

    html = f"""
    <html>
    <body>
        <p>Dear AI-ML Team,</p>
        <p>The PowerBI dashboard URL for user ID '{user_id}', product '{product}' and user_type '{user_type}' could not be found.</p>
        <p>Please take necessary actions.</p>
        <p>Regards,<br>BI-Bot</p>
    </body>
    </html>
    """

    part2 = MIMEText(html, "html")
    message.attach(part2)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, message.as_string())


DATABASE = 'appdata/powerbi_dashboard.db'
def get_db():
    os.makedirs('appdata', exist_ok=True)
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def create_table():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bi_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product TEXT,
            user_type TEXT,
            url TEXT
        )
    ''')
    db.commit()


@app.post('/store_url')
def store_url(product, user_id, user_type, url):
    product = product.upper()
    user_type = user_type.upper()
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT id FROM bi_reports WHERE user_id = ? AND product = ? AND user_type = ?', (user_id, product, user_type))
    existing_row = cursor.fetchone()
    if existing_row:
        cursor.execute('UPDATE bi_reports SET url = ? WHERE id = ?', (url, existing_row['id']))
        db.commit()
        return {'message': 'URL Updated successfully'}
    else:
        cursor.execute('INSERT INTO bi_reports (user_id, product, user_type, url) VALUES (?, ?, ?, ?)', (user_id, product, user_type, url))
        db.commit()
        return {'message': 'URL stored successfully'}


@app.get('/get_url')
def get_url(user_id, product, user_type):
    product = product.upper()
    user_type = user_type.upper()
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT url FROM bi_reports WHERE user_id=? AND product=? AND user_type=?', (user_id, product, user_type))
    result = cursor.fetchone()

    if result:
        return {"status":"Success",
                "url": result['url']}
    else:
        send_email(user_id, product, user_type)
        return {"status":"failure"}


from io import BytesIO
@app.post('/upload_excel')
async def upload_excel(file: UploadFile = File(...)):
    if not file.filename.endswith('.xlsx'):
        return {"error": "Only Excel files (.xlsx) are allowed."}
    try:
        contents = await file.read()
        excel_file = BytesIO(contents)
        df = pd.read_excel(excel_file)
        for _, row in df.iterrows():
            store_url(row['product'], row['user_id'], row['user_type'], row['url'])
        return {"message": "Excel data successfully stored in the database."}
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}

    
@app.get('/get_all_data')
def get_all_data():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM bi_reports')
    rows = cursor.fetchall()
    data = []
    for row in rows:
        data.append({
            'id': row['id'],
            'user_id': row['user_id'],
            'product': row['product'],
            'user_type': row['user_type'],
            'url': row['url']
        })
    return {'data': data}


@app.delete('/delete_data')
def delete_data(user_id: int, product: str, user_type: str):
    product = product.upper()
    user_type = user_type.upper()
    db = get_db()
    cursor = db.cursor()
    cursor.execute('DELETE FROM bi_reports WHERE user_id=? AND product=? AND user_type=?', (user_id, product, user_type))
    db.commit()
    if cursor.rowcount > 0:
        return {"message": "Data deleted successfully"}
    else:
        return {"message": "No matching data found for deletion"}


# # ################################################### Checklist Comparison ####################################
# from datetime import date, datetime
# from copy import deepcopy
# import base64
# import uuid
# import ast

# from Exp_checklist_automation.sql3DB import get_city_state_country
# from Exp_checklist_automation.main import compare_process_pdfss, create_process_pdfs
# from Exp_checklist_automation.data_store import *
# from Exp_checklist_automation.checklist_extractor import upload_pdf_to_s3bucket
# from Exp_checklist_automation.sql3DB import create_checklist_automation_table



# def pdf_to_base64(file_path):
#     with open(file_path, 'rb') as file:
#         file_bytes = base64.b64encode(file.read())
#         base_64 = file_bytes.decode("ascii")
#     return base_64 



# def get_financial_year(country: str) -> str:
#     country = country.upper().strip()
#     today = datetime.now()

#     if country == 'IN' :
#         if today.month >= 4:
#             start_year = today.year
#             end_year = today.year + 1
#             return f"{start_year}-{end_year}"
#         else:                  
#             start_year = today.year - 1
#             end_year = today.year
#             return f"{start_year}-{end_year}"
        
#     return today.year


# WORK_DIR = "runs"
    
# @app.post("/compareChecklist")
# async def compare_pdfs(
#     checklist: UploadFile = File(...),
#     invoice: UploadFile = File(...),
#     jobNo: Optional[str] = Form(None),
#     fleetId: Optional[int] = Form(0),
#     loadId: Optional[int] = Form(0),
#     referenceNo: Optional[str] = Form(None),
#     tradeType: str = Form("SE"),
#     lat: Optional[float] = Form(None),
#     lon: Optional[float] = Form(None),
#     country: str = Form("ROW")
# ):
    
#     _, _, countryy = get_city_state_country(lat, lon)
#     country = country.upper().strip()
#     country = 'IN' if country == 'IN' else 'ROW'    

#     activity, product = get_activity_product(tradeType)

#     os.makedirs(WORK_DIR, exist_ok=True)
#     job_id = str(uuid.uuid4())
#     job_dir = os.path.join(WORK_DIR, job_id)
#     os.makedirs(job_dir)
#     financialYear = get_financial_year(country)
#     checklist_path = os.path.join(job_dir, checklist.filename)
#     invoice_path = os.path.join(job_dir, invoice.filename)
#     output_pdf = os.path.join(job_dir, "comparison.pdf")

#     # Save uploaded files
#     with open(checklist_path, "wb") as f:
#         shutil.copyfileobj(checklist.file, f)

#     with open(invoice_path, "wb") as f:
#         shutil.copyfileobj(invoice.file, f)

#     # Validate checklist page count
#     reader = PdfReader(checklist_path)
#     page_count = len(reader.pages)

#     print(f"Checklist page count: {page_count}")

#     if page_count > 5:
#         shutil.rmtree(job_dir, ignore_errors=True)

#         return {
#             "status": "failure",
#             "message": f"Checklist contains {page_count} pages. Maximum allowed is 5 pages."
#         }
        
#     details = {
#         'checklist_path' : checklist_path,
#         'invoice_path' : invoice_path,
#         'product' : product,
#         'output_pdf' : output_pdf,
#         'activity' : activity,
#         'job_no' : jobNo,
#         'fleet_id' : fleetId,
#         'load_id' : loadId,
#         'financial_year' : financialYear,
#         'trade_type' : tradeType,
#         'lat' : lat,
#         'lon' : lon
#     }    
     

#     compare_process_pdfss(details)

#     ts = int(round(time.time() * 1000))
    
#     product_info = {
#         "activity" : activity,
#         "product" : product,
#         "financial_year" : financialYear,
#         "country" : country
#     }
    
#     upload_pdf_to_s3bucket(checklist_path, f"{product.title()}/{activity.title()}/{jobNo}_{financialYear}_CHECKLIST.pdf", ts=ts, is_template=False, product_info=product_info)
#     upload_pdf_to_s3bucket(invoice_path, f"{product.title()}/{activity.title()}/{jobNo}_{financialYear}_INV.pdf", ts=ts, is_template=False, product_info=product_info)
#     if activity == "EXPORT":
#         upload_pdf_to_s3bucket(output_pdf, f"{product.title()}/{activity.title()}/{jobNo}_{financialYear}_SB_CompareTemplate.pdf", ts=ts, is_template=True, product_info=product_info)
#     else:
#         upload_pdf_to_s3bucket(output_pdf, f"{product.title()}/{activity.title()}/{jobNo}_{financialYear}_BOE_CompareTemplate.pdf", ts=ts, is_template=True, product_info=product_info)

#     invoice_pdf = pdf_to_base64(invoice_path)
#     checklist_pdf = pdf_to_base64(checklist_path)

#     shutil.rmtree("runs")

#     return {
#         "status" : "success",
#         "inv_pdf" : invoice_pdf,
#         "pkglist_pdf" : checklist_pdf,
#         "jobNo" : jobNo,
#         "referenceNo" : referenceNo,
#         "activity" : activity,
#         "product" : product,
#     }


# ######################################### Create Checklist #########################################
# @app.post("/createChecklist")
# async def create(
#     invoice: UploadFile = File(...),
#     jobNo: Optional[str] = Form(None),
#     fleetId: Optional[int] = Form(0),
#     loadId: Optional[int] = Form(0),
#     referenceNo: Optional[str] = Form(None),
#     tradeType: Optional[str] = Form(None),
#     lat: Optional[float] = Form(None),
#     lon: Optional[float] = Form(None),
#     country: str = Form("ROW")
# ):
    
#     os.makedirs(WORK_DIR, exist_ok=True)
#     job_id = str(uuid.uuid4())
#     job_dir = os.path.join(WORK_DIR, job_id)
#     os.makedirs(job_dir)
    
#     country = country.upper().strip()
#     invoice_path = os.path.join(job_dir, invoice.filename)
#     output_pdf = os.path.join(job_dir, "comparison.pdf")
    
#     activity, product = get_activity_product(tradeType)    
#     _, _, countryy = get_city_state_country(lat, lon)

#     country = 'IN' if country == 'IN' else 'ROW'
#     financialYear = get_financial_year(country)

#     # Save uploaded files
#     with open(invoice_path, "wb") as f:
#         shutil.copyfileobj(invoice.file, f)
        
        
#     create_info = {
#     "invoice_path": invoice_path,
#     "output_pdf": output_pdf,
#     "product": product,
#     "activity": activity,
#     "job_no": jobNo,
#     "fleet_id": fleetId,
#     "load_id": loadId,
#     "financial_year": financialYear,
#     "trade_type": tradeType,
#     "lat": lat,
#     "lon": lon
#     }

#     create_process_pdfs(create_info)

#     ts = int(round(time.time() * 1000))
#     product_info = {
#         'activity' : activity,
#         'product' : product,
#         'financial_year' : financialYear,
#         'country' : country
#     }
    
#     if activity == "EXPORT":
#         upload_pdf_to_s3bucket(output_pdf, f"eblCL/{product.title()}/{activity.title()}/{jobNo}_{financialYear}_SB_Checklist.pdf", ts=ts, is_template=True, product_info=product_info)
#     else:
#         upload_pdf_to_s3bucket(output_pdf, f"eblCL/{product.title()}/{activity.title()}/{jobNo}_{financialYear}_BOE_Checklist.pdf", ts=ts, is_template=True, product_info=product_info)

#     invoice_pdf = pdf_to_base64(invoice_path)
#     comparison_pdf = pdf_to_base64(output_pdf)

#     shutil.rmtree("runs")
    
#     return {
#         "status" : "success",
#         "inv_pdf" : comparison_pdf,
#         "jobNo" : jobNo,
#         "referenceNo" : referenceNo,
#         "activity" : activity,
#         "product" : product,            
#         }


# ########################### get Checklist Template from S3 ###########################
# @app.get('/geteauditSBTemp')
# def get_s3_template(
#     jobNo=None,
#     financialYear="2025-2026",
#     pdfType="create",
#     tradeType = "SE",
#     referenceNo = None,
#     lat=None,
#     lon=None,
#     country='ROW'
# ):
#     activity, product = get_activity_product(tradeType)  
#     country = country.upper().strip()
#     country = 'IN' if country == 'IN' else 'ROW'

#     os.makedirs("output_pdf", exist_ok=True)
#     activity = activity.title()
#     product = product.title()
#     typ = "SB" if activity == "Export" else "BOE"
#     bucket_name = creds.S3_BUCKET_NAME
#     s3_client = boto3.client(
#         "s3",
#         aws_access_key_id=creds.bl_aws_access_key_id,
#         aws_secret_access_key=creds.bl_aws_secret_access_key,
#         region_name="ap-south-1"
#     )
#     try:
#         #  COMPARE 
#         if pdfType == "compare":
#             files = {
#                 "compare_pdf": {
#                     "s3": f"{product}/{activity}/{jobNo}_{financialYear}_{typ}_CompareTemplate.pdf",
#                     "local": f"output_pdf/{typ}_CompareTemplate.pdf"},

#                 "checklist_pdf": {
#                     "s3": f"{product}/{activity}/{jobNo}_{financialYear}_CHECKLIST.pdf",
#                     "local": f"output_pdf/CHECKLIST.pdf"},

#                 "inv_pdf": {
#                     "s3": f"{product}/{activity}/{jobNo}_{financialYear}_INV.pdf",
#                     "local": f"output_pdf/INV.pdf"}}
            
#             result = {}
#             for key, value in files.items():
                
#                 s3_path = value["s3"]
#                 if country == 'ROW' :
#                     s3_path = f'ROW/{value["s3"]}'

#                 s3_client.download_file(bucket_name, s3_path ,value["local"])
#                 result[key] = pdf_to_base64(value["local"])
                
#             return {
#                 "status": "success",
#                 "jobNo": jobNo,
#                 "tradeType": tradeType,
#                 "referenceNo": referenceNo,
#                 **result
#             }
#         #  CREATE 
#         else:
#             s3_key = f"eblCL/{product}/{activity}/{jobNo}_{financialYear}_{typ}_Checklist.pdf"
#             if country == 'ROW' :
#                 s3_key = f'ROW/{s3_key}'
            
#             file_object = f"output_pdf/{typ}Checklist.pdf"
#             print(f"S3 KEY : {s3_key}")
#             s3_client.download_file(bucket_name,s3_key,file_object)
#             return {
#                 "status": "success",
#                 "jobNo": jobNo,
#                 "tradeType": tradeType,
#                 "referenceNo": referenceNo,                
#                 "template": pdf_to_base64(file_object),

#             }
#     except Exception as e:
#         print(e)
#         return {
#             "status": "failure"
#         }


########################### Create tables on startup ########################### 
@app.get("/getDatabase")
def get_users(table: str):
    conn = sqlite3.connect(r"appdata/powerbi_dashboard.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table}")
    rows = cursor.fetchall()
    data = [dict(row) for row in rows]
    conn.close()
    return {"data": data}
    

@app.on_event("startup")
def run_allfun() :
    create_table()
    _ensure_table(get_db_path())
    create_mbl_table()
    create_checklist_automation_table()


if __name__ == '__main__':
    uvicorn.run("main:app", host="0.0.0.0", port=8000, timeout_keep_alive=90)