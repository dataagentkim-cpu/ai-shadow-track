# shortlist + 뉴스만 보고 블라인드로 포트폴리오 판단을 내리는 LLM 모듈 (나의 보유 종목은 절대 미포함)
import json

import anthropic

import config

_DECISION_TOOL = {
    "name": "submit_portfolio_decision",
    "description": "이번 주 포트폴리오 판단을 제출한다. 지난주와 동일하게 전량 유지(무거래)도 유효한 제출이다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "stock_code": {"type": "string"},
                        "stock_name": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": ["확대", "유지", "축소", "매도"],
                            "description": "확대=신규 편입 또는 비중 증가, 유지=지난주와 동일 비중, 축소=비중 일부 감소, 매도=전량 청산",
                        },
                        "target_weight": {"type": "number", "description": "포트폴리오 내 목표 비중 (%, 0~100). 매도면 0."},
                        "rationale": {"type": "string", "description": "이 판단을 내린 이유 (자연어). 오늘 시점 기준으로만 설명할 것"},
                        "conviction": {"type": "string", "enum": ["상", "중", "하"]},
                    },
                    "required": ["stock_code", "stock_name", "action", "target_weight", "rationale", "conviction"],
                },
            }
        },
        "required": ["decisions"],
    },
}

_SYSTEM_PROMPT = f"""당신은 국내주식(코스피+코스닥) 전문 포트폴리오 매니저입니다.
매주 이 포트폴리오를 계속 운용하며, shortlist·뉴스·지난주 당신 자신의 포트폴리오를 참고해
이번 주 목표 포트폴리오를 결정합니다.

판단 프레이밍 (반드시 지킬 것):
- 지난주 보유 종목이 있다면 각각을 "오늘 이 가격에 새로 산다면 살 것인가?" 기준으로 재평가하세요.
- 매수가나 지금까지의 수익률은 제공되지 않으며, 판단 근거로 삼아서도 안 됩니다. "이미 벌었으니
  익절해야 한다"거나 "손실 중이니 만회할 때까지 버텨야 한다"는 식의 사고는 전형적인 앵커링·처분효과
  편향이며 이 판단에서는 배제해야 합니다. 오직 지금 시점의 펀더멘털·모멘텀·뉴스만으로 새로 평가하세요.
- 지난주와 완전히 동일한 포트폴리오를 그대로 유지("전량 유지, 무거래")하는 것도 완전히 유효하고
  정상적인 결정입니다. 근거 없이 매주 포트폴리오를 흔들 필요가 없습니다 — 오히려 그게 잘못된 신호입니다.
- 지난주 보유 종목이 이번 주 shortlist에서 빠졌다면 스크리너가 매력도 저하로 판단했다는 뜻이니
  참고하되, 최종 판단(유지할지 매도할지)은 당신이 내립니다.
- {config.TARGET_STOCK_MIN}~{config.TARGET_STOCK_MAX}개 종목을 유지하고 목표비중 합은 100%에 맞추세요.
- 특정 섹터에 집중하고 싶다면 그렇게 하되, 왜 그런 판단을 내렸는지 논리와 확신도를 반드시 남기세요.
- 스크리너가 이미 위생/중복/쏠림 정리를 마친 shortlist이므로, 이 안에서 자유롭게 선택하면 됩니다.
- 당신은 어떤 개인의 실제 보유 종목도 알지 못하며 알 필요가 없습니다. 아래 "지난주 포트폴리오"는
  당신 자신이 지난주에 내린 판단일 뿐, 실제 개인 계좌와는 무관합니다. 순수하게 이 데이터만으로
  판단하세요."""


def _build_user_prompt(
    shortlist: list[dict],
    news_by_stock: dict,
    market_news: list[dict],
    previous_portfolio: list[dict] | None = None,
) -> str:
    lines = []
    if previous_portfolio:
        lines.append("## 지난주 당신의 포트폴리오 (매수가·수익률 비공개 — 오늘 가격 기준으로 새로 평가할 것)\n")
        for p in previous_portfolio:
            lines.append(f"- {p['stock_name']}({p['stock_code']}): 목표비중 {p['target_weight']:.1f}%")
        lines.append("")
    else:
        lines.append("## 지난주 포트폴리오: 없음 (이번이 첫 판단, 백지에서 시작)\n")

    lines.append("## Shortlist 종목\n")
    for s in shortlist:
        lines.append(f"- {s['stock_name']}({s['stock_code']}): 90일 수익률 {s['momentum_score']:+.1%}")
        for n in news_by_stock.get(s["stock_name"], [])[:3]:
            lines.append(f"    · {n['title']}")
    lines.append("\n## 시장 전반 뉴스\n")
    for n in market_news[:5]:
        lines.append(f"- {n['title']}")
    return "\n".join(lines)


def judge(
    shortlist: list[dict],
    news_by_stock: dict,
    market_news: list[dict],
    previous_portfolio: list[dict] | None = None,
) -> list[dict]:
    client = anthropic.Anthropic()
    user_prompt = _build_user_prompt(shortlist, news_by_stock, market_news, previous_portfolio)

    response = client.messages.create(
        model=config.LLM_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        tools=[_DECISION_TOOL],
        tool_choice={"type": "tool", "name": "submit_portfolio_decision"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_portfolio_decision":
            return block.input["decisions"]

    raise RuntimeError("LLM이 구조화된 판단을 반환하지 않음")


if __name__ == "__main__":
    sample_shortlist = [{"stock_code": "005930", "stock_name": "삼성전자", "momentum_score": 0.05}]
    print(json.dumps(judge(sample_shortlist, {}, []), ensure_ascii=False, indent=2))
