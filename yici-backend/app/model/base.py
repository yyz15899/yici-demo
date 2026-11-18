"""模型客户端统一接口。

mock 与真实模型实现同一接口，analysis.py 只依赖此抽象，
切换 MODEL_BACKEND 或测试注入 FakeClient 都不需要改业务代码。
"""

from ..schemas import AnalyzeRequest, LocatedEvidence, ModelAnalysis


class BaseModelClient:
    """模型客户端基类。

    analyze 接收已通过前置校验的请求与已定位证据，返回固定结构 ModelAnalysis。
    实现方负责把底层失败映射为三类异常：
    ModelNotConfiguredError / ModelTimeoutError / ModelInvalidOutputError。
    """

    async def analyze(self, req: AnalyzeRequest, evidence: list[LocatedEvidence]) -> ModelAnalysis:
        raise NotImplementedError