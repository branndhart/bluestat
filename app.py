from flask import Flask, render_template, request
import aiohttp
import asyncio
import os
import json
import math
from dotenv import load_dotenv

app = Flask(__name__)
load_dotenv()

API_TOKEN = os.environ.get("API_TOKEN")


async def fetch(url, session):
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    try:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                print(f"Ошибка при запросе: {url}, статус: {response.status}")
                return None
            return await response.json()
    except Exception as e:
        print(f"Ошибка при запросе к API: {e}")
        return None


async def get_player_id(nickname, session):
    player_url = f"https://open.faceit.com/data/v4/players?nickname={nickname}"
    data = await fetch(player_url, session)
    if not data:
        print(f"Ошибка: не найден игрок с ником {nickname}")
        return None
    return data.get("player_id")

async def get_player_image(nickname, session):
    player_url = f"https://open.faceit.com/data/v4/players?nickname={nickname}"
    data = await fetch(player_url, session)
    if data:
        return data.get("avatar") or ""  # Если нет аватара, возвращаем пустую строку
    return ""



async def get_player_elo(nickname, session):
    player_url = f"https://open.faceit.com/data/v4/players?nickname={nickname}"
    data = await fetch(player_url, session)
    if data:
        return data.get("games", {}).get("cs2", {}).get("faceit_elo", 0)
    return 0


async def get_match_stats(match_id, player_id, session):
    match_stats_url = f"https://open.faceit.com/data/v4/matches/{match_id}/stats"
    match_data = await fetch(match_stats_url, session)

    if match_data:
        for team in match_data.get("rounds", [])[0].get("teams", []):
            for player in team.get("players", []):
                if player.get("player_id") == player_id:
                    stats = player.get("player_stats", {})
                    return {
                        "kills": int(stats.get("Kills", 0)),
                        "deaths": int(stats.get("Deaths", 0)),
                        "headshots": int(stats.get("Headshots", 0)),
                        "kd_ratio": float(stats.get("K/D Ratio", 0.0)),
                        "entry_success": float(stats.get("Match Entry Success Rate", 0.0)),
                        "adr": float(stats.get("ADR", 0.0)),
                    }
    return None


async def get_last_matches_stats(player_id, session, limit=20):
    matches_url = f"https://open.faceit.com/data/v4/players/{player_id}/history?game=cs2&limit={limit}"
    match_data = await fetch(matches_url, session)
    if not match_data:
        return []

    matches = match_data.get("items", [])
    tasks = []
    for match in matches:
        match_id = match.get("match_id")
        task = asyncio.create_task(get_match_stats(match_id, player_id, session))
        tasks.append(task)

    match_stats = await asyncio.gather(*tasks)
    return [stats for stats in match_stats if stats]


async def calculate_firepower(stats, double_kills=0, triple_kills=0, quadro_kills=0, penta_kills=0):
    kd_ratio = stats.get("kd_ratio", 1.0)
    adr = stats.get("adr", 75.0)
    hs_percent = stats.get("headshots", 50.0)
    entry_success_rate = stats.get("entry_success", 50.0)

    multi_kill_score = (
        (double_kills * 2) + (triple_kills * 3) + (quadro_kills * 4) + (penta_kills * 5)
    )
    firepower = (
        (kd_ratio * 35)
        + (adr * 25)
        + (hs_percent * 10)
        + (entry_success_rate * 10)
        + (multi_kill_score * 20)
    )
    return min(firepower / 40, 100)


def calculate_averages(matches_stats):
    total_kills = sum([match["kills"] for match in matches_stats])
    total_deaths = sum([match["deaths"] for match in matches_stats])
    total_headshots = sum([match["headshots"] for match in matches_stats])
    total_kd_ratio = sum([match["kd_ratio"] for match in matches_stats])
    total_entry_success = sum([match["entry_success"] for match in matches_stats])
    total_adr = sum([match["adr"] for match in matches_stats])

    match_count = len(matches_stats)
    if match_count == 0:
        return 0, 0, 0, 0, 0

    avg_kills = total_kills / match_count
    avg_hs = (total_headshots / total_kills) * 100 if total_kills > 0 else 0
    avg_kd = total_kd_ratio / match_count
    avg_entry_success = total_entry_success / match_count
    avg_adr = total_adr / match_count

    return avg_kills, avg_hs, avg_kd, avg_entry_success, avg_adr


async def get_player_stats(nickname):
    async with aiohttp.ClientSession() as session:
        player_id = await get_player_id(nickname, session)
        if not player_id:
            return None

        matches_stats = await get_last_matches_stats(player_id, session, limit=20)
        if not matches_stats:
            return None

        avg_kills, avg_hs, avg_kd, avg_entry_success, avg_adr = calculate_averages(
            matches_stats
        )
        firepower = await calculate_firepower(
            {
                "kd_ratio": avg_kd,
                "adr": avg_adr,
                "headshots": avg_hs,
                "entry_success": avg_entry_success,
            }
        )
        elo = await get_player_elo(nickname, session)
        
        player_image = await get_player_image(nickname, session)

        return {
            "nickname": nickname,
            "elo": elo,
            "adr": math.ceil(avg_adr),
            "hs_percentage": math.ceil(avg_hs),  # округление вверх
            "avg_kills": math.ceil(avg_kills),  # округление вверх
            "entry_success": math.ceil(
                avg_entry_success * 100
            ),  # умножаем на 100 и округляем вверх
            "kd_ratio": round(avg_kd, 2),
            "firepower": round(firepower, 2),
            "player_image": player_image
        }


def run_async(nickname):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(get_player_stats(nickname))


@app.route("/gamercard/<string:nickname>")
def gamercard(nickname):
    player_stats = run_async(nickname)
    return render_template("gamercard.html", stats=player_stats)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
