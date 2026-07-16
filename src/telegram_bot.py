# AI 투자 판단 섀도우 트랙 결과를 텔레그램으로 질의응답하는 봇 (long-polling)
import asyncio
import datetime
import logging
import os

import pytz
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from db import get_connection

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
log = logging.getLogger("shadowtrack")

KST = pytz.timezone("Asia/Seoul")

_ALLOWED_CHAT_ID = os.getenv("TELEGRAM_ALLOWED_CHAT_ID")

_TRACK_LABEL = {
    config.TRACK_MY_HOLDINGS: "① 내 보유",
    config.TRACK_AI_BLIND: "② AI 백지",
    config.TRACK_INDEX: "③ 지수",
}


async def _guard(update: Update) -> bool:
    if _ALLOWED_CHAT_ID and str(update.effective_chat.id) != _ALLOWED_CHAT_ID:
        await update.message.reply_text("이 봇은 지정된 채팅에서만 사용할 수 있습니다.")
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    await update.message.reply_text(
        "AI 투자 판단 섀도우 트랙 봇입니다.\n\n"
        "/performance - 3파전 최신 수익률\n"
        "/latest - 이번 주 AI 블라인드 판단\n"
        "/history - 최근 8주 수익률 추이\n"
        "/why 종목명 - 특정 종목에 대한 최근 판단 이유\n"
        "/holdings - 내 실제 보유 스냅샷"
    )


async def cmd_performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    conn = get_connection()
    rows = conn.execute(
        """SELECT s.* FROM snapshots s
           JOIN (SELECT track_id, MAX(snapshot_date) AS max_date FROM snapshots GROUP BY track_id) latest
           ON s.track_id = latest.track_id AND s.snapshot_date = latest.max_date"""
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("아직 벤치마크 스냅샷이 없습니다. run_weekly를 먼저 실행하세요.")
        return

    lines = [f"3파전 수익률 (기준일: {rows[0]['snapshot_date']})\n"]
    for r in sorted(rows, key=lambda x: _TRACK_LABEL.get(x["track_id"], x["track_id"])):
        label = _TRACK_LABEL.get(r["track_id"], r["track_id"])
        lines.append(f"{label}: {r['return_pct']:+.2%} ({r['portfolio_value']:,.0f}원)")
    await update.message.reply_text("\n".join(lines))


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    conn = get_connection()
    latest_week = conn.execute(
        "SELECT week_id FROM decisions WHERE track_id = ? ORDER BY decision_date DESC LIMIT 1",
        (config.TRACK_AI_BLIND,),
    ).fetchone()
    if not latest_week:
        await update.message.reply_text("아직 AI 판단 로그가 없습니다.")
        conn.close()
        return

    rows = conn.execute(
        "SELECT * FROM decisions WHERE track_id = ? AND week_id = ? ORDER BY target_weight DESC",
        (config.TRACK_AI_BLIND, latest_week["week_id"]),
    ).fetchall()
    conn.close()

    lines = [f"AI 블라인드 판단 ({latest_week['week_id']})\n"]
    for r in rows:
        lines.append(
            f"- {r['stock_name']} [{r['action']}] {r['target_weight']:.1f}% (확신도 {r['conviction']})\n"
            f"    {r['rationale']}"
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    conn = get_connection()
    rows = conn.execute(
        """SELECT track_id, snapshot_date, return_pct FROM snapshots
           ORDER BY snapshot_date DESC LIMIT 24"""
    ).fetchall()
    conn.close()

    by_date = {}
    for r in rows:
        by_date.setdefault(r["snapshot_date"], {})[r["track_id"]] = r["return_pct"]

    lines = ["최근 수익률 추이 (내보유 / AI백지 / 지수)\n"]
    for date in sorted(by_date.keys(), reverse=True)[:8]:
        d = by_date[date]
        lines.append(
            f"{date}: "
            f"{d.get(config.TRACK_MY_HOLDINGS, 0):+.1%} / "
            f"{d.get(config.TRACK_AI_BLIND, 0):+.1%} / "
            f"{d.get(config.TRACK_INDEX, 0):+.1%}"
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_why(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("사용법: /why 종목명 (예: /why 삼성전자)")
        return
    query = " ".join(context.args)

    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM decisions WHERE stock_name LIKE ?
           ORDER BY decision_date DESC LIMIT 5""",
        (f"%{query}%",),
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(f"'{query}' 관련 판단 로그를 찾지 못했습니다.")
        return

    lines = [f"'{query}' 관련 최근 판단\n"]
    for r in rows:
        label = _TRACK_LABEL.get(r["track_id"], r["track_id"])
        lines.append(
            f"[{r['week_id']} / {label}] {r['action']} {r['target_weight']:.1f}% (확신도 {r['conviction']})\n"
            f"    {r['rationale']}"
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_holdings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    conn = get_connection()
    rows = conn.execute("SELECT * FROM holdings ORDER BY snapshot_value DESC").fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("holdings 시딩이 아직 안 되었습니다 (seed_holdings.py 실행 필요).")
        return

    total = sum(r["snapshot_value"] for r in rows)
    lines = [f"내 실제 보유 스냅샷 ({rows[0]['snapshot_date']}, 총 {total:,.0f}원)\n"]
    for r in rows:
        lines.append(f"- {r['stock_name']}: {r['quantity']}주, 비중 {r['snapshot_weight']:.1%}")
    await update.message.reply_text("\n".join(lines))


async def decision_job(context: ContextTypes.DEFAULT_TYPE):
    """매주 화요일 07:00 KST(장 시작 전) — 월요일 종가+뉴스 기준으로 판단만 내린다."""
    import run_weekly

    log.info("주간 판단 시작")
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, run_weekly.run_decision)
    except Exception as e:
        log.exception("주간 판단 실패: %s", e)
        if _ALLOWED_CHAT_ID:
            await context.bot.send_message(chat_id=_ALLOWED_CHAT_ID, text=f"주간 판단 실행 실패: {e}")
        return

    if not _ALLOWED_CHAT_ID:
        return

    lines = [f"이번 주 AI 블라인드 판단 완료 ({result['week_id']}) — 체결은 장 시작 후 반영됩니다\n"]
    for d in result["decisions"]:
        lines.append(f"- {d['stock_name']} [{d['action']}] {d['target_weight']:.1f}% (확신도 {d['conviction']})")
    await context.bot.send_message(chat_id=_ALLOWED_CHAT_ID, text="\n".join(lines))


async def execution_job(context: ContextTypes.DEFAULT_TYPE):
    """매주 화요일 09:05 KST(장 시작 후) — 실제 당일 시가 기준으로 체결/벤치마크를 확정한다."""
    import run_weekly

    log.info("주간 체결 시작")
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, run_weekly.run_execution)
    except Exception as e:
        log.exception("주간 체결 실패: %s", e)
        if _ALLOWED_CHAT_ID:
            await context.bot.send_message(chat_id=_ALLOWED_CHAT_ID, text=f"주간 체결 실행 실패: {e}")
        return

    if not _ALLOWED_CHAT_ID:
        return

    lines = [f"이번 주 체결/벤치마크 완료 ({result['week_id']})\n"]
    for b in result["benchmark"]:
        label = _TRACK_LABEL.get(b["track_id"], b["track_id"])
        lines.append(f"{label}: {b['return_pct']:+.2%}")
    await context.bot.send_message(chat_id=_ALLOWED_CHAT_ID, text="\n".join(lines))


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 미설정 (.env 확인)")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("performance", cmd_performance))
    app.add_handler(CommandHandler("latest", cmd_latest))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("why", cmd_why))
    app.add_handler(CommandHandler("holdings", cmd_holdings))

    # python-telegram-bot의 JobQueue.run_daily days는 0=일요일 ~ 6=토요일 순서라 화요일은 2다.
    TUESDAY = 2
    app.job_queue.run_daily(
        decision_job, time=datetime.time(7, 0, 0, tzinfo=KST), days=(TUESDAY,), name="weekly_decision"
    )
    app.job_queue.run_daily(
        execution_job, time=datetime.time(9, 5, 0, tzinfo=KST), days=(TUESDAY,), name="weekly_execution"
    )

    print("텔레그램 Q&A 봇 시작 (Ctrl+C로 종료)")
    app.run_polling()


if __name__ == "__main__":
    main()
