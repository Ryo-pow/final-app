from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from vercel_blob import put
import os
import requests # 外部と通信するために追加

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"Hello": "World"}

# --- ここから新しい機能 ---
@app.get("/weather/")
def get_weather(latitude: float = Query(...), longitude: float = Query(...)):
    """
    指定された緯度経度の天気予報をOpen-Meteo APIから取得する
    """
    try:
        # Open-Meteo APIのURLを組み立て
        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia%2FTokyo"
        
        # Open-Meteoに天気予報を問い合わせる
        response = requests.get(url)
        response.raise_for_status()  # エラーがあれば例外を発生させる
        
        weather_data = response.json()
        
        return JSONResponse(status_code=200, content=weather_data)

    except requests.exceptions.RequestException as e:
        return JSONResponse(status_code=500, content={"message": f"API request failed: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"An error occurred: {str(e)}"})
# --- ここまで新しい機能 ---


@app.post("/upload-image/")
async def upload_image(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        blob_result = put(
            file.filename,
            contents,
            options={
                'add_random_suffix': True,
                'access': 'public'
            }
        )
        return JSONResponse(
            status_code=200,
            content={
                "message": "Image uploaded successfully!",
                "url": blob_result['url']
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"message": f"An error occurred: {str(e)}"}
        )
