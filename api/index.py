# Responseクラスとjsonライブラリを新しくインポートします
from fastapi import FastAPI, File, UploadFile, Query, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import json

from vercel_blob import put
import os
import requests
from tavily import TavilyClient
import google.generativeai as genai

# --- APIキーの設定 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

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
        
        # FastAPIのJSONResponseは、自動的にUTF-8へエンコードし、適切なContent-Typeヘッダーを付与します。
        # これにより、手動でのエンコード処理が不要になり、コードがシンプルになります。
        return JSONResponse(content={"answer": response.text})

    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"An error occurred: {str(e)}"})

# --- AI旅行プラン最適化機能 ---
@app.get("/plan-trip/")
async def plan_trip(
    destinations: str = Query(..., description="カンマ区切りの目的地リスト"),
    start_lat: float = Query(..., description="出発点の緯度"),
    start_lon: float = Query(..., description="出発点の経度")
):
    try:
        destination_names = [dest.strip() for dest in destinations.split(',')]
        
        # --- ステップ1: 全地点の緯度・経度を特定 ---
        headers = {'User-Agent': 'FinalApp/1.0 (https://github.com/your-repo)'} # Nominatimのポリシーに従いUser-Agentを設定
        locations = [{"name": "現在地", "lat": start_lat, "lon": start_lon}]
        
        for name in destination_names:
            # 日本国内に絞って検索
            search_query = f"{name}, 日本"
            nominatim_url = f"https://nominatim.openstreetmap.org/search?q={search_query}&format=json&limit=1"
            response = requests.get(nominatim_url, headers=headers)
            response.raise_for_status()
            geo_data = response.json()
            if not geo_data:
                return JSONResponse(status_code=404, content={"message": f"目的地が見つかりませんでした: {name}"})
            
            locations.append({
                "name": name,
                "lat": float(geo_data[0]["lat"]),
                "lon": float(geo_data[0]["lon"])
            })

        # --- ステップ2: 天気予報の取得 ---
        first_dest = locations[1] # 最初の目的地
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={first_dest['lat']}&longitude={first_dest['lon']}&daily=weathercode,temperature_2m_max,precipitation_probability_max&timezone=Asia%2FTokyo"
        weather_response = requests.get(weather_url)
        weather_response.raise_for_status()
        weather_data = weather_response.json().get('daily', {})
        weather_info = f"天気予報: 最高気温 {weather_data.get('temperature_2m_max', ['N/A'])[0]}℃, 降水確率 {weather_data.get('precipitation_probability_max', ['N/A'])[0]}%"

        # --- ステップ3: 各地点間の移動時間を計算 ---
        coords_str = ";".join([f"{loc['lon']},{loc['lat']}" for loc in locations])
        osrm_url = f"http://router.project-osrm.org/table/v1/driving/{coords_str}"
        osrm_response = requests.get(osrm_url)
        osrm_response.raise_for_status()
        durations_matrix = osrm_response.json()['durations']

        # --- ステップ4: AIへの「超・詳細な指示」 ---
        prompt = f"""
        # 役割
        あなたは日本の交通事情と気象に詳しい、最高の旅行プランナーです。

        # 提供データ
        1. 目的地リスト: {[loc['name'] for loc in locations]}
        2. 各地点間の移動時間（秒）のテーブル: {durations_matrix}
           (テーブルのインデックスは上記の目的地リストのインデックスに対応します)
        3. 今日の天気: {weather_info}

        # 指示
        これらの情報に基づき、日本国内を最速で移動するための、最も効率的な1日の観光プランを日本語で作成してください。
        特に、一般的な交通渋滞（朝夕のラッシュアワーなど）や天候の影響も考慮に入れて、訪問順序とスケジュールを提案してください。
        
        # 出力形式のルール
        - プランは訪問順にリスト形式で出力してください。
        - なぜそのルートが最速だと判断したのか、理由を「ルートのポイント」として簡潔に一言で付け加えてください。
        
        例:
        【AI最適化プラン】
        1. 現在地 → 〇〇博物館 (移動時間: 約20分)
        2. 〇〇博物館 → △△公園 (移動時間: 約30分)
        3. △△公園 → ××タワー (移動時間: 約15分)

        ルートのポイント: 渋滞の多い中心部を避けるルートです。
        """
        
        ai_response = model.generate_content(prompt)
        
        return JSONResponse(content={"plan": ai_response.text})

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
