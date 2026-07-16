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
    config.TRACK_VALUE: "②a 가치",
    config.TRACK_MOMENTUM: "②b 모멘텀",
    config.TRACK_QUALITY: "②c 퀄리티",
    config.TRACK_FREE: "②d 자유형",
    config.TRACK_INDEX: "③ 지수",
    config.TRACK_EQUAL_WEIGHT: "④ 동일가중",
    config.TRACK_AI_BLIND: "② AI(구버전)",
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
        "/performance - 4파전 최신 수익률\n"
        "/latest - 이번 주 AI 판단\n"
        "/history - 최근 8주 수익률 추이\n"
        "/why 종목명 - 특정 종목에 대한 최근 판단 이유\n"
        "/holdings - 내 실제 보유 스냅샷\n"
        "/alpha - AI가 동일가중 baseline 대비 실제로 값을 했는지(②−④ 스프레드)\n"
        "/risk - 트랙별 위험조정 지표(Sharpe/Sortino/MDD/베타/알파 등)"
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

    lines = [f"트랙별 최신 수익률 (기준일: {rows[0]['snapshot_date']})\n"]
    for r in sorted(rows, key=lambda x: _TRACK_LABEL.get(x["track_id"], x["track_id"])):
        label = _TRACK_LABEL.get(r["track_id"], r["track_id"])
        lines.append(f"{label}: {r['return_pct']:+.2%} ({r['portfolio_value']:,.0f}원)")
    await update.message.reply_text("\n".join(lines))


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    conn = get_connection()

    any_sent = False
    for track_id in config.LENS_TRACKS:
        latest_week = conn.execute(
            "SELECT week_id FROM decisions WHERE track_id = ? ORDER BY decision_date DESC LIMIT 1",
            (track_id,),
        ).fetchone()
        if not latest_week:
            continue
        any_sent = True

        rows = conn.execute(
            "SELECT * FROM decisions WHERE track_id = ? AND week_id = ? ORDER BY target_weight DESC",
            (track_id, latest_week["week_id"]),
        ).fetchall()

        label = _TRACK_LABEL.get(track_id, track_id)
        lines = [f"{label} 판단 ({latest_week['week_id']})"]
        if track_id == config.TRACK_FREE and rows and rows[0]["weekly_perspective"]:
            lines.append(f"이번 주 관점: {rows[0]['weekly_perspective']}")
        lines.append("")
        for r in rows:
            lines.append(
                f"- {r['stock_name']} [{r['action']}] {r['target_weight']:.1f}% (확신도 {r['conviction']})\n"
                f"    {r['rationale']}"
            )
        await update.message.reply_text("\n".join(lines))

    conn.close()
    if not any_sent:
        await update.message.reply_text("아직 AI 판단 로그가 없습니다.")


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

    track_order = [
        config.TRACK_MY_HOLDINGS, *config.LENS_TRACKS, config.TRACK_INDEX, config.TRACK_EQUAL_WEIGHT,
    ]
    header = " / ".join(_TRACK_LABEL[t] for t in track_order)
    lines = [f"최근 수익률 추이 ({header})\n"]
    for date in sorted(by_date.keys(), reverse=True)[:8]:
        d = by_date[date]
        values = " / ".join(f"{d.get(t, 0):+.1%}" for t in track_order)
        lines.append(f"{date}: {values}")
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


async def cmd_alpha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """②x(각 렌즈)가 ④(동일가중 baseline)를 못 이기면 LLM 판단이 값을 못 하는 것 — 그 스프레드."""
    if not await _guard(update):
        return
    import benchmark

    any_sent = False
    for track_id in config.LENS_TRACKS:
        spread = benchmark.get_alpha_spread(track_id)
        if not spread:
            continue
        any_sent = True

        label = _TRACK_LABEL.get(track_id, track_id)
        latest = spread[-1]
        lines = [
            f"{label} vs 동일가중 baseline(④) 스프레드 ({latest['week_id']})\n",
            f"이번 주: {latest['weekly_spread']:+.2%}",
            f"누적: {latest['cumulative_spread']:+.2%}\n",
            "최근 추이 (주간 / 누적):",
        ]
        for s in spread[-8:]:
            lines.append(f"{s['date']}: {s['weekly_spread']:+.2%} / {s['cumulative_spread']:+.2%}")
        await update.message.reply_text("\n".join(lines))

    if not any_sent:
        await update.message.reply_text("아직 ②/④ 둘 다 스냅샷이 없습니다.")


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    conn = get_connection()
    rows = conn.execute(
        """SELECT r.* FROM risk_metrics r
           JOIN (SELECT track_id, MAX(snapshot_date) AS max_date FROM risk_metrics GROUP BY track_id) latest
           ON r.track_id = latest.track_id AND r.snapshot_date = latest.max_date"""
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("아직 위험조정 지표가 없습니다.")
        return

    def _fmt(v, pct=True):
        if v is None:
            return "N/A"
        return f"{v:+.2%}" if pct else f"{v:.2f}"

    lines = [f"트랙별 위험조정 지표 (기준일: {rows[0]['snapshot_date']})\n"]
    for r in sorted(rows, key=lambda x: _TRACK_LABEL.get(x["track_id"], x["track_id"])):
        label = _TRACK_LABEL.get(r["track_id"], r["track_id"])
        lines.append(
            f"{label}\n"
            f"  주간수익 {_fmt(r['weekly_return'])} | 연율화변동성 {_fmt(r['ann_volatility'])}\n"
            f"  Sharpe {_fmt(r['sharpe'], False)} | Sortino {_fmt(r['sortino'], False)} | MDD {_fmt(r['mdd'])}\n"
            f"  적중률 {_fmt(r['hit_rate'])}"
            + (f" | 회전율 {_fmt(r['turnover'])}" if r["turnover"] is not None else "")
            + (f" | 베타 {_fmt(r['beta'], False)}" if r["beta"] is not None else "")
            + (f" | 알파 {_fmt(r['alpha'])}" if r["alpha"] is not None else "")
            + (f" | 최대클러스터비중 {_fmt(r['top_cluster_weight_pct'])}" if r["top_cluster_weight_pct"] is not None else "")
        )
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

    lines = [f"이번 주 4렌즈 판단 완료 ({result['week_id']}) — 체결은 장 시작 후 반영됩니다\n"]
    for track_id, decisions in result["decisions_by_lens"].items():
        label = _TRACK_LABEL.get(track_id, track_id)
        lines.append(f"[{label}]")
        for d in decisions:
            lines.append(f"- {d['stock_name']} [{d['action']}] {d['target_weight']:.1f}% (확신도 {d['conviction']})")
        lines.append("")
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
    app.add_handler(CommandHandler("alpha", cmd_alpha))
    app.add_handler(CommandHandler("risk", cmd_risk))

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
