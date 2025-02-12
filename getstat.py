from flask import Flask, render_template, request
import aiohttp
import asyncio
import os
import json
from dotenv import load_dotenv

app = Flask(__name__)
load_dotenv()

API_TOKEN = os.environ.get("API_TOKEN")


async def fetch(url, session):
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    async with session.get(url, headers=headers) as response:
        if response.status != 200:
            print(f"Ошибка при запросе: {url}, статус: {response.status}")
        return await response.json()


async def get_player_id(nickname, session):
    player_url = f"https://open.faceit.com/data/v4/players?nickname={nickname}"
    data = await fetch(player_url, session)
    if not data:
        print(f"Ошибка: не найден игрок с ником {nickname}")
    return data.get("player_id")


async def get_match_stats(match_id, player_id, session):
    match_stats_url = f"https://open.faceit.com/data/v4/matches/{match_id}/stats"
    match_data = await fetch(match_stats_url, session)

    all_stats = []  # Список для хранения всех статистических данных

    # Пройдемся по всем раундам и всем игрокам
    for round_data in match_data.get("rounds", []):
        for team in round_data.get("teams", []):
            for player in team.get("players", []):
                if player.get("player_id") == player_id:
                    stats = player.get("player_stats", {})
                    all_stats.append(stats)

    # Сортировка статистики игроков по ключам (по алфавиту)
    sorted_all_stats = [{k: stats[k] for k in sorted(stats)} for stats in all_stats]

    return sorted_all_stats if all_stats else None


async def get_last_matches_stats(player_id, session, limit=20):
    matches_url = f"https://open.faceit.com/data/v4/players/{player_id}/history?game=cs2&limit={limit}"
    match_data = await fetch(matches_url, session)
    matches = match_data.get("items", [])

    tasks = []
    for match in matches:
        match_id = match.get("match_id")
        task = asyncio.create_task(get_match_stats(match_id, player_id, session))
        tasks.append(task)

    match_stats = await asyncio.gather(*tasks)

    # Суммирование статистики по всем матчам
    total_stats = {
        "1v1Count": 0,
        "1v1Wins": 0,
        "1v2Count": 0,
        "1v2Wins": 0,
        "ADR": 0,
        "Assists": 0,
        "Clutch Kills": 0,
        "Damage": 0,
        "Deaths": 0,
        "Double Kills": 0,
        "Enemies Flashed": 0,
        "Entry Count": 0,
        "Entry Wins": 0,
        "First Kills": 0,
        "Flash Count": 0,
        "Flash Success Rate per Match": 0,
        "Flash Successes": 0,
        "Flashes per Round in a Match": 0,
        "Headshots": 0,
        "Headshots %": 0,
        "K/D Ratio": 0,
        "K/R Ratio": 0,
        "Kills": 0,
        "Knife Kills": 0,
        "MVPs": 0,
        "Match 1v1 Win Rate": 0,
        "Match 1v2 Win Rate": 0,
        "Match Entry Rate": 0,
        "Match Entry Success Rate": 0,
        "Penta Kills": 0,
        "Pistol Kills": 0,
        "Quadro Kills": 0,
        "Result": 0,
        "Sniper Kill Rate per Match": 0,
        "Sniper Kill Rate per Round": 0,
        "Sniper Kills": 0,
        "Triple Kills": 0,
        "Utility Count": 0,
        "Utility Damage": 0,
        "Utility Damage Success Rate per Match": 0,
        "Utility Damage per Round in a Match": 0,
        "Utility Enemies": 0,
        "Utility Success Rate per Match": 0,
        "Utility Successes": 0,
        "Utility Usage per Round": 0,
        "Zeus Kills": 0,
    }

    match_count = 0
    for stats in match_stats:
        if isinstance(stats, list):
            for stat in stats:
                for key, value in stat.items():
                    if key in total_stats:
                        total_stats[key] += float(value)
                match_count += 1
        elif isinstance(stats, dict):
            for key, value in stats.items():
                if key in total_stats:
                    total_stats[key] += float(value)
            match_count += 1

    # Не усредняем указанные вами значения
    no_average_keys = [
        "1v1Count",
        "1v1Wins",
        "1v2Count",
        "1v2Wins",
        "Assists",
        "Clutch Kills",
        "Deaths",
        "Double Kills",
        "Enemies Flashed",
        "Entry Count",
        "Entry Wins",
        "First Kills",
        "Flash Count",
        "Headshots",
        "Kills",
        "Knife Kills",
        "MVPs",
        "Penta Kills",
        "Pistol Kills",
        "Quadro Kills",
        "Sniper Kills",
        "Triple Kills",
        "Utility Count",
        "Utility Damage",
        "Sniper Kill Rate per Match",
        "Sniper Kill Rate per Round",
        "Utility Damage per Round in a Match",
        "Utility Enemies",
        "Utility Successes",
        "Utility Usage per Round",
        "Zeus Kills",
    ]

    # Для этих значений не усредняем, только суммируем
    for key in no_average_keys:
        total_stats[key] = round(total_stats[key], 0)  # Округляем до целого, если нужно

    # Для остальных статистик (которые нужно усреднить) делаем среднее
    if match_count > 0:
        for key in total_stats:
            if key not in no_average_keys:  # Это не усредняем
                total_stats[key] /= match_count

    # Вычисляем проценты для 1v1 и 1v2
    if total_stats["1v1Count"] > 0:
        total_stats["1v1WinRate"] = (
            total_stats["1v1Wins"] / total_stats["1v1Count"]
        ) * 100
    if total_stats["1v2Count"] > 0:
        total_stats["1v2WinRate"] = (
            total_stats["1v2Wins"] / total_stats["1v2Count"]
        ) * 100

    return total_stats


async def get_player_rank(player_id, session, region="EU", game_id="cs2"):
    ranking_url = f"https://open.faceit.com/data/v4/rankings/games/{game_id}/regions/{region}/players/{player_id}"
    ranking_data = await fetch(ranking_url, session)
    return ranking_data.get("position")


async def calculate_firepower(stats):
    kd_ratio = stats.get("K/D Ratio", 1.0)
    adr = stats.get("ADR", 75.0)
    hs_percent = stats.get("Headshots %", 50.0)
    entry_success_rate = stats.get("Match Entry Success Rate", 50.0)
    double_kills = stats.get("Double Kills", 0)
    triple_kills = stats.get("Triple Kills", 0)
    quadro_kills = stats.get("Quadro Kills", 0)
    penta_kills = stats.get("Penta Kills", 0)

    # Шаг 1: Подсчет Multi-kill Score
    multi_kill_score = (
        (double_kills * 2) + (triple_kills * 3) + (quadro_kills * 4) + (penta_kills * 5)
    )

    # Шаг 2: Подставляем в формулу
    firepower_raw = (
        (kd_ratio * 35)
        + (adr * 25)
        + (hs_percent * 10)
        + (entry_success_rate * 10)
        + (multi_kill_score * 20)
    )

    # Шаг 3: Нормализация к 100
    firepower = firepower_raw / 40
    return min(firepower, 100)  # Ограничиваем значение до 100


async def main():
    nickname = "donk666"
    async with aiohttp.ClientSession() as session:
        player_id = await get_player_id(nickname, session)
        if not player_id:
            print(f"Не удалось получить player_id для {nickname}")
            return

        # Получаем суммированные статистики
        data = await get_last_matches_stats(player_id, session)
        if data:
            firepower = await calculate_firepower(data)
            data["Firepower"] = firepower

            print(nickname)
            print(json.dumps(data, indent=4, ensure_ascii=False))


asyncio.run(main())
