# Responseクラスとjsonライブラリを新しくインポートします
from fastapi import FastAPI, File, UploadFile, Query, Response, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import asyncio
import httpx

from vercel_blob import put
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
async def get_weather(latitude: float = Query(...), longitude: float = Query(...)):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia%2FTokyo"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            weather_data = response.json()
            return JSONResponse(status_code=200, content=weather_data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"An error occurred: {str(e)}"})

# --- AI検索機能 ---
@app.get("/ai-search/")
async def ai_search(query: str = Query(...)):
    try:
        context = tavily.search(query=query, search_depth="advanced")
        prompt = f"""
        以下の検索結果を参考にして、ユーザーの質問に日本語で分かりやすく答えてください。
        ユーザーの質問: {query}
        検索結果: {context}
        """
        response = await model.generate_content_async(prompt)
        return JSONResponse(content={"answer": response.text})

    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"An error occurred: {str(e)}"})

# --- AI旅行プラン最適化機能 (最終決定版) ---
@app.get("/create-itinerary/")
async def create_itinerary(request: Request):
    try:
        params = request.query_params
        destinations = params.get("destinations")
        date = params.get("date")
        durations_str = params.get("durations")
        start_lat_str = params.get("start_lat")
        start_lon_str = params.get("start_lon")

        if not all([destinations, date, durations_str, start_lat_str, start_lon_str]):
            return JSONResponse(status_code=400, content={"message": "Missing required query parameters: destinations, date, durations, start_lat, start_lon"})

        start_lat = float(start_lat_str)
        start_lon = float(start_lon_str)
        destination_names = [dest.strip() for dest in destinations.split(',')]
        durations = [int(d.strip()) for d in durations_str.split(',')]

        if len(destination_names) != len(durations):
            return JSONResponse(status_code=400, content={"message": "The number of destinations and durations must be the same."})

        headers = {'User-Agent': 'FinalApp/1.0 (ryo-pow)'}
        locations = [{"name": "現在地", "lat": start_lat, "lon": start_lon}]
        dest_details = []

        async with httpx.AsyncClient() as client:
            geocoding_tasks = []
            for name in destination_names:
                search_query = f"{name}, 日本"
                url = f"https://nominatim.openstreetmap.org/search?q={search_query}&format=json&limit=1"
                geocoding_tasks.append(client.get(url, headers=headers))
            
            geocoding_responses = await asyncio.gather(*geocoding_tasks)

            for i, response in enumerate(geocoding_responses):
                response.raise_for_status()
                geo_data = response.json()
                if not geo_data:
                    return JSONResponse(status_code=404, content={"message": f"目的地が見つかりませんでした: {destination_names[i]}"})
                
                lat = float(geo_data[0]["lat"])
                lon = float(geo_data[0]["lon"])
                locations.append({"name": destination_names[i], "lat": lat, "lon": lon})
                dest_details.append({"name": destination_names[i], "duration_minutes": durations[i]})

            first_dest = locations[1]
            weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={first_dest['lat']}&longitude={first_dest['lon']}&daily=weathercode,temperature_2m_max,precipitation_probability_max&timezone=Asia%2FTokyo&start_date={date}&end_date={date}"
            
            coords_str = ";".join([f"{loc['lon']},{loc['lat']}" for loc in locations])
            osrm_driving_url = f"http://router.project-osrm.org/table/v1/driving/{coords_str}"
            osrm_walking_url = f"http://router.project-osrm.org/table/v1/walking/{coords_str}"

            weather_task = client.get(weather_url)
            osrm_driving_task = client.get(osrm_driving_url)
            osrm_walking_task = client.get(osrm_walking_url)

            weather_response, osrm_driving_response, osrm_walking_response = await asyncio.gather(weather_task, osrm_driving_task, osrm_walking_task)
            weather_response.raise_for_status()
            osrm_driving_response.raise_for_status()
            osrm_walking_response.raise_for_status()

            weather_data = weather_response.json().get('daily', {})
            weather_info = f"天気予報: 最高気温 {weather_data.get('temperature_2m_max', ['N/A'])[0]}℃, 降水確率 {weather_data.get('precipitation_probability_max', ['N/A'])[0]}%"
            durations_driving_matrix = osrm_driving_response.json()['durations']
            durations_walking_matrix = osrm_walking_response.json()['durations']

        prompt = f"""
        # 役割
        あなたは、車と徒歩を組み合わせた旅行計画の達人です。

        # 提供データ
        1. 目的地と希望滞在時間（分）のリスト: {dest_details}
        2. 旅行日: {date}
        3. その日の天気: {weather_info}
        4. 全地点のリスト（インデックス0は現在地）: {[loc['name'] for loc in locations]}
        5. 車での各地点間の移動時間（秒）テーブル: {durations_driving_matrix}
        6. 徒歩での各地点間の移動時間（秒）テーブル: {durations_walking_matrix}
           (移動時間テーブルのインデックスは、全地点リストのインデックスに対応します)

        # 指示
        これらの情報に基づき、日本国内を移動するための、最も効率的な1日の観光プランを日本語で作成してください。
        ユーザー指定の滞在時間を考慮して、現実的なタイムスケジュール（例: 10:00-10:30）を提案してください。
        一般的な交通渋滞（時間帯や日付）や天候、駐車の難易度なども考慮し、各区間で「車で移動」すべきか、「近くの駐車場に停めて徒歩で移動」すべきかを判断してください。
        
        # 出力形式のルール
        - プランは訪問順に、タイムスケジュールを含めてリスト形式で出力してください。
        - 各移動区間では、(車)や(徒歩)のように移動手段を明記してください。
        - なぜそのルートが最適だと判断したのか、理由を「ルートのポイント」として簡潔に一言で付け加えてください。
        """
        
        ai_response = await model.generate_content_async(prompt)
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
