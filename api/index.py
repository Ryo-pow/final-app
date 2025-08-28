from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from vercel_blob import put
import os
import requests
from tavily import TavilyClient
import google.generativeai as genai

# --- APIキーをVercelの金庫から読み込む ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# --- 各サービスを使えるように設定 ---
genai.configure(api_key=GEMINI_API_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

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

# --- 天気予報機能 ---
@app.get("/weather/")
def get_weather(latitude: float = Query(...), longitude: float = Query(...)):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia%2FTokyo"
        response = requests.get(url)
        response.raise_for_status()
        weather_data = response.json()
        return JSONResponse(status_code=200, content=weather_data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"An error occurred: {str(e)}"})

# --- AI検索機能 ---
@app.get("/ai-search/")
def ai_search(query: str = Query(...)):
    try:
        context = tavily.search(query=query, search_depth="advanced")
        prompt = f"""
        以下の検索結果を参考にして、ユーザーの質問に日本語で分かりやすく答えてください。
        
        ユーザーの質問: {query}
        
        検索結果: {context}
        """
        response = model.generate_content(prompt)
        
        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        # ↓↓↓ この一行を変更しました！ ↓↓↓
        return {"answer": response.text}
        # ↑↑↑ この一行を変更しました！ ↑↑↑
        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"An error occurred: {str(e)}"})

# --- 画像アップロード機能 ---
@app.post("/upload-image/")
async def upload_image(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        blob_result = put(
            file.filename,
            contents,
            options={'add_random_suffix': True, 'access': 'public'}
        )
        return JSONResponse(
            status_code=200,
            content={"message": "Image uploaded successfully!", "url": blob_result['url']}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"message": f"An error occurred: {str(e)}"}
        )
