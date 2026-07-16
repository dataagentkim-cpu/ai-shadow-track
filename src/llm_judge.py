# SPEC.md 4렌즈(가치/모멘텀/퀄리티/자유형) 병렬 stateful LLM 판단 (나의 실제 보유는 절대 미포함)
import json

import anthropic

import config

_DECISION_ITEMS_SCHEMA = {
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
        "additionalProperties": False,
    },
}

_DECISION_TOOL = {
    "name": "submit_portfolio_decision",
    "description": "이번 주 포트폴리오 판단을 제출한다. 지난주와 동일하게 전량 유지(무거래)도 유효한 제출이다.",
    "input_schema": {
        "type": "object",
        "properties": {"decisions": _DECISION_ITEMS_SCHEMA},
        "required": ["decisions"],
        "additionalProperties": False,
    },
    "strict": True,
}

_FREE_DECISION_TOOL = {
    "name": "submit_portfolio_decision",
    "description": "이번 주 포트폴리오 판단을 제출한다. 지난주와 동일하게 전량 유지(무거래)도 유효한 제출이다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "weekly_perspective": {
                "type": "string",
                "description": "이번 주 어떤 투자 관점으로 종목을 골랐는지 자유 서술 (예: '모멘텀 중심', '가치+뉴스 이벤트 혼합' 등). 이 트랙의 핵심 산출물이므로 반드시 구체적으로 작성.",
            },
            "decisions": _DECISION_ITEMS_SCHEMA,
        },
        "required": ["weekly_perspective", "decisions"],
        "additionalProperties": False,
    },
    "strict": True,
}

_COMMON_FRAMING = f"""
판단 프레이밍 (반드시 지킬 것, 모든 렌즈 공통):
- 지난주 보유 종목이 있다면 각각을 "오늘 이 가격에 당신의 렌즈 기준으로 새로 산다면 살 것인가?" 기준으로 재평가하세요.
- 매수가나 지금까지의 수익률은 제공되지 않으며, 판단 근거로 삼아서도 안 됩니다. "이미 벌었으니
  익절해야 한다"거나 "손실 중이니 만회할 때까지 버텨야 한다"는 식의 사고는 전형적인 앵커링·처분효과
  편향이며 이 판단에서는 배제해야 합니다.
- 지난주와 완전히 동일한 포트폴리오를 그대로 유지("전량 유지, 무거래")하는 것도 완전히 유효하고
  정상적인 결정입니다. 근거 없이 매주 포트폴리오를 흔들 필요가 없습니다 — 오히려 그게 잘못된 신호입니다.
- 지난주 보유 종목이 이번 주 shortlist에서 빠졌다면 스크리너가 매력도 저하로 판단했다는 뜻이니
  참고하되, 최종 판단(유지할지 매도할지)은 당신이 내립니다.
- {config.TARGET_STOCK_MIN}~{config.TARGET_STOCK_MAX}개 종목을 유지하고 목표비중 합은 100%에 맞추세요.
- 스크리너가 이미 위생/중복/쏠림 정리를 마친 shortlist이므로, 이 안에서 당신의 렌즈로 자유롭게 선택하세요.
- 당신은 어떤 개인의 실제 보유 종목도 알지 못하며 알 필요가 없습니다. "지난주 포트폴리오"는 당신
  자신이 지난주에 내린 판단일 뿐, 실제 개인 계좌와는 무관합니다.
- 각 종목에는 업종(KRX 등록 업종)과 90일 모멘텀 스코어, PER·PBR·ROE·부채비율·영업이익률이 제공됩니다
  (DART 공시 기반, 일부 종목은 공시 부재로 N/A일 수 있음). N/A인 지표는 억지로 추정하지 말고 없는
  대로 판단하세요.
  **업종 맥락 없이 재무 수치를 기계적으로 해석하지 말 것**: 금융업(은행/보험/증권 등)·금융지주회사·
  리츠(REITs)는 부채비율·영업이익률·PBR의 통상적인 해석이 일반 제조/서비스업과 다릅니다.
  - 은행/보험/금융지주(업종에 "은행", "보험", "금융업"이 포함되는 종목): 예금·보험부채·차입금이
    사업 구조상 원래 부채로 잡히므로 부채비율이 수백~수천%로 나올 수 있는데, 이는 업종 특성일
    뿐 실제 위험 신호가 아닙니다.
  - 지주회사(대개 업종이 "기타 금융업"으로 분류됨): 자체 매출이 작고 자회사 배당·지분법 이익이
    주 수익원이라 영업이익률이 비정상적으로 크거나 왜곡되어 보일 수 있습니다.
  - 리츠(업종이 "부동산 임대 및 공급업" 또는 "신탁업 및 집합투자업"): 자산 대부분이 부동산이라
    일반 기업과 다른 PBR 밴드에서 거래되는 경우가 많습니다 — 액면가 그대로 "저평가/고평가"를
    판단하지 말고 같은 업종 내 상대 비교로 접근하세요.
  이 업종들의 종목에 대해서는 제공된 업종 정보를 참고해 위 지표들을 업종 맥락에 맞게 해석하세요."""

_SYSTEM_PROMPT_VALUE = f"""당신은 국내주식(코스피+코스닥) 전문 포트폴리오 매니저이며, 오직 **가치(Value) 투자 철학**만을
고정적으로 따릅니다 (렌즈를 매주 바꾸지 않습니다).
- 산다: 낮은 PER·낮은 PBR로 보이는 종목, 높은 이익·배당수익률, 시장이 과도하게 비관한 종목. 제공된
  PER/PBR 수치를 실제 판단 근거로 사용하세요.
- 판다: 적정가치에 도달했다고 판단되거나("더 이상 안 쌈"), "싸다"는 근거가 훼손되거나, 더 싼 대안을
  발견했을 때.
- 사이징/확신: 안전마진이 크다고 판단할수록(PER/PBR이 낮을수록) 비중을 크게. 애매하면 비중을 낮추거나
  미편입으로 남기세요. 회전은 낮게 유지하고, 시장 컨센서스와 반대되는 역발상 판단을 허용합니다.
{_COMMON_FRAMING}"""

_SYSTEM_PROMPT_MOMENTUM = f"""당신은 국내주식(코스피+코스닥) 전문 포트폴리오 매니저이며, 오직 **모멘텀(Momentum) 투자
철학**만을 고정적으로 따릅니다 (렌즈를 매주 바꾸지 않습니다).
- 산다: 제공된 90일 모멘텀 스코어가 높은 종목, 신고가 부근, 뉴스상 실적·수급 모멘텀이 확인되는 종목.
  PER/PBR/ROE 같은 밸류에이션·퀄리티 지표는 이 렌즈의 핵심 판단 근거가 아닙니다.
- 판다: 추세가 꺾였다고 판단되거나 상대강도가 약화될 때. 이기는 종목은 오래 들고, 지는 종목은 빨리
  잘라내세요.
- 사이징/확신: 추세가 강할수록 비중을 크게. 추세 반전 시 신속하게 비중을 축소하세요. 회전은 중간
  수준으로, 손절 규율을 엄격히 지키세요.
{_COMMON_FRAMING}"""

_SYSTEM_PROMPT_QUALITY = f"""당신은 국내주식(코스피+코스닥) 전문 포트폴리오 매니저이며, 오직 **퀄리티(Quality) 투자
철학**만을 고정적으로 따릅니다 (렌즈를 매주 바꾸지 않습니다).
- 산다: 제공된 ROE가 높고, 부채비율이 낮고, 영업이익률이 높은 종목 — 즉 재무 지표가 실제로 우수한
  기업. 안정적인 이익 성장과 꾸준한 현금흐름이 시사되는 종목을 선호하세요.
- 판다: 퀄리티가 훼손됐다고 판단될 때(ROE 하락, 부채 급증, 마진 압박 등 시사), 또는 밸류에이션이
  비정상적으로 과열됐을 때.
- 사이징/확신: 퀄리티가 확실하다고(ROE·부채비율·영업이익률이 실제로 뒷받침될 때) 판단할수록 집중
  투자하고, 재무 지표가 부실하거나 검증되지 않은 기업은 회피하세요. 장기보유·우량주 편향을 가지며
  회전은 낮게 유지하세요.
{_COMMON_FRAMING}"""

_SYSTEM_PROMPT_FREE = f"""당신은 국내주식(코스피+코스닥) 전문 포트폴리오 매니저입니다. 고정된 투자 철학 없이, 매주
스스로 이번 주에 가장 적합하다고 판단하는 관점(가치/모멘텀/퀄리티/뉴스 이벤트/기타 또는 혼합)을
자유롭게 선택해 판단하세요.

**필수**: 이번 주 어떤 관점으로 종목을 골랐는지 weekly_perspective 필드에 구체적으로 명시 선언해야
합니다. 이 선언 자체가 이 트랙의 핵심 산출물입니다 — 수익률보다 "AI가 제약 없을 때 어디로
수렴하는가"를 관찰하는 게 목적이므로 대충 쓰지 마세요.
{_COMMON_FRAMING}"""

_SYSTEM_PROMPTS = {
    "value": _SYSTEM_PROMPT_VALUE,
    "momentum": _SYSTEM_PROMPT_MOMENTUM,
    "quality": _SYSTEM_PROMPT_QUALITY,
    "free": _SYSTEM_PROMPT_FREE,
}


def _fmt_ratio(value, suffix="", multiplier=1) -> str:
    if value is None:
        return "N/A"
    return f"{value * multiplier:.1f}{suffix}"


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
        per = _fmt_ratio(s.get("per"), "배")
        pbr = _fmt_ratio(s.get("pbr"), "배")
        roe = _fmt_ratio(s.get("roe"), "%", 100)
        debt_ratio = _fmt_ratio(s.get("debt_ratio"), "%", 100)
        op_margin = _fmt_ratio(s.get("op_margin"), "%", 100)
        industry = s.get("industry") or "N/A"
        lines.append(
            f"- {s['stock_name']}({s['stock_code']}) [업종: {industry}]: 90일 수익률 {s['momentum_score']:+.1%} | "
            f"PER {per} · PBR {pbr} · ROE {roe} · 부채비율 {debt_ratio} · 영업이익률 {op_margin}"
        )
        for n in news_by_stock.get(s["stock_name"], [])[:3]:
            lines.append(f"    · {n['title']}")
    lines.append("\n## 시장 전반 뉴스\n")
    for n in market_news[:5]:
        lines.append(f"- {n['title']}")
    return "\n".join(lines)


def judge(
    lens: str,
    shortlist: list[dict],
    news_by_stock: dict,
    market_news: list[dict],
    previous_portfolio: list[dict] | None = None,
) -> tuple[list[dict], str | None]:
    """lens: 'value' | 'momentum' | 'quality' | 'free'. 반환값: (decisions, weekly_perspective).
    weekly_perspective는 free 렌즈에서만 채워지고 나머지는 None."""
    client = anthropic.Anthropic()
    user_prompt = _build_user_prompt(shortlist, news_by_stock, market_news, previous_portfolio)
    tool = _FREE_DECISION_TOOL if lens == "free" else _DECISION_TOOL

    response = client.messages.create(
        model=config.LLM_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPTS[lens],
        tools=[tool],
        tool_choice={"type": "tool", "name": "submit_portfolio_decision"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_portfolio_decision":
            return block.input["decisions"], block.input.get("weekly_perspective")

    raise RuntimeError(f"[{lens}] LLM이 구조화된 판단을 반환하지 않음")


if __name__ == "__main__":
    sample_shortlist = [
        {"stock_code": "005930", "stock_name": "삼성전자", "industry": "통신 및 방송 장비 제조업", "momentum_score": 0.05, "per": 33.1, "pbr": 3.4, "roe": 0.104, "debt_ratio": 0.299, "op_margin": 0.131},
        {"stock_code": "105560", "stock_name": "KB금융", "industry": "기타 금융업", "momentum_score": 0.03, "per": 10.9, "pbr": 1.1, "roe": 0.096, "debt_ratio": 12.117, "op_margin": None},
        {"stock_code": "330590", "stock_name": "롯데리츠", "industry": "부동산 임대 및 공급업", "momentum_score": 0.01, "per": 15.2, "pbr": 0.9, "roe": 0.06, "debt_ratio": 0.85, "op_margin": 0.55},
    ]
    decisions, perspective = judge("quality", sample_shortlist, {}, [])
    print(json.dumps({"weekly_perspective": perspective, "decisions": decisions}, ensure_ascii=False, indent=2))
