"""确定性模拟模型：不依赖任何外部服务，用于首版联调。

逻辑完全基于本次提交的材料做通用词面比较，不针对任何样例文章写死；
mock 不判定正确答案（supported_option 恒为 None），正确答案判定留给真实模型。
"""

import re

from ..schemas import (
    AnalyzeRequest,
    DiffItem,
    LocatedEvidence,
    ModelAnalysis,
    QuoteOut,
)
from .base import BaseModelClient

STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "any", "can", "had",
    "her", "was", "one", "our", "out", "has", "have", "been", "were", "they",
    "this", "that", "with", "from", "its", "who", "what", "when", "where",
    "which", "why", "how", "than", "then", "them", "their", "there", "these",
    "those", "still", "used", "into", "over", "after", "before",
    "during", "about", "would", "could", "should", "does", "did", "will",
}
UNIVERSAL = {"all", "every", "always", "never", "none", "only", "entire", "whole"}
PURPOSE_MARKERS = {"example", "examples", "instance", "illustrate", "illustrates", "such"}
CAUSAL_MARKERS = {"because", "caused", "causes", "led", "due", "therefore", "result", "results", "so"}


def _words(text: str) -> list[str]:
    """提取内容词：小写英文词，去停用词与短词。保留 all/some 等限定词用于范围检测。"""
    return [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS and len(w) > 2]


def _sentences(text: str) -> list[str]:
    """按句末标点切分原文句子（用于引文候选与统计）。"""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _snippet(quote: str, limit: int = 40) -> str:
    """截取引文片段嵌入追问，保证不同证据句产生不同追问文本。"""
    return quote if len(quote) <= limit else quote[:limit] + "…"


class MockModelClient(BaseModelClient):
    """确定性模拟模型客户端：相同输入必得相同输出，便于联调与测试。"""

    async def analyze(self, req: AnalyzeRequest, evidence: list[LocatedEvidence]) -> ModelAnalysis:
        """基于本次材料做通用词面比较，生成差异、引文、解释与追问。

        追问按作答依据分支：猜的/记不清→只引导重新找依据（definitive=False）；
        排除法→标记两项各自多说的内容；有证据→追问内嵌所圈句子片段，
        因此圈对句与圈错句天然得到不同追问。
        """
        options = {o.id.upper(): o.text for o in req.options}
        student, compare = req.student_choice.upper(), req.compare_choice.upper()
        s_words, c_words = _words(options[student]), _words(options[compare])
        s_set, c_set = set(s_words), set(c_words)

        differences: list[DiffItem] = []
        # 词面差集：错项独有词=“多说了”，比较项独有词=“漏说了”；无差集则提示可能答偏
        added = [w for w in s_words if w not in c_set]
        omitted = [w for w in c_words if w not in s_set]
        if added:
            differences.append(DiffItem(
                kind="added",
                detail_zh=f"选项 {student} 比 {compare} 多提到了 “{', '.join(dict.fromkeys(added[:4]))}”，"
                          f"请核对原文是否真的支持这些多出的内容。",
            ))
        if omitted:
            differences.append(DiffItem(
                kind="omitted",
                detail_zh=f"选项 {compare} 提到而 {student} 漏掉了 “{', '.join(dict.fromkeys(omitted[:4]))}”，"
                          f"请核对这些内容是否正是题干所问。",
            ))
        if not differences:
            differences.append(DiffItem(
                kind="shifted",
                detail_zh=f"两个选项用词相近，但回答的问题可能不同：请对照题干本身，看 {student} 是否答偏了。",
            ))

        issue_types: list[str] = []
        # 三类问题的词面信号：全称限定词→范围；举例标记→目的；因果连接词→因果
        if (s_set & UNIVERSAL) - c_set:
            issue_types.append("scope")
        article_words = set(_words(req.article_text))
        if (s_set | c_set) & PURPOSE_MARKERS and PURPOSE_MARKERS & article_words:
            issue_types.append("purpose")
        if s_set & CAUSAL_MARKERS:
            issue_types.append("causality")
        if req.focus_kind and req.focus_kind not in issue_types:
            issue_types.append(req.focus_kind)

        sentences = _sentences(req.article_text)
        # 引文只取自已提交的证据与原文真实句子，保证全部可逐字定位
        quotes: list[QuoteOut] = [
            QuoteOut(
                text=ev.quote, start=ev.start, end=ev.end,
                option_id=student, note_zh="你圈出的依据",
            )
            for ev in evidence
        ]
        best = None
        best_score = 0
        for sent in sentences:
            score = len(set(_words(sent)) & c_set)
            if score > best_score:
                best, best_score = sent, score
        if best:
            best = best[:1000]
            if best not in {q.text for q in quotes}:
                quotes.append(QuoteOut(text=best, option_id=compare, note_zh=f"与选项 {compare} 用词最接近的原文引文"))
        quotes = quotes[:6]

        explanation = (
            f"选项 {student} 与 {compare} 的词面差异见上方列表。"
            f"原文共 {len(sentences)} 句，你提交了 {len(evidence)} 处依据。"
            f"以上为自动建议，请逐句对照原文自行核实。"
        )

        basis = req.answer_basis
        if basis in ("guess", "dont_remember"):
            follow_up = "先不推断错因：请重读原文，把两个选项各自对应的句子圈出来，再比较它们多说了什么。"
            definitive = False
        elif basis == "elimination":
            follow_up = "最后剩下哪两项？我们把它们各自多说的内容标出来，再回到原文找依据。"
            definitive = True
        elif evidence:
            ev = evidence[0]
            ev_words = set(_words(ev.quote))
            snippet = _snippet(ev.quote)
            if len(ev_words & c_set) > len(ev_words & s_set):
                follow_up = (
                    f"你圈的这句「{snippet}」更接近选项 {compare} 的说法："
                    f"它写的是谁、哪些情况？请对照选项 {student} 的主语和范围再读一遍。"
                )
            else:
                follow_up = (
                    f"你圈的「{snippet}」给了什么信息？原文哪一句直接写了选项 {student} "
                    f"声称的行为或结果？找不到就说明它多说了。"
                )
            definitive = True
        else:
            follow_up = "请先在原文中圈出你认为支持自己选择的句子，再提交依据。"
            definitive = False

        return ModelAnalysis(
            differences=differences,
            quotes=quotes,
            explanation_zh=explanation,
            follow_up_zh=follow_up,
            issue_types=issue_types,
            supported_option=None,
            definitive=definitive,
        )
