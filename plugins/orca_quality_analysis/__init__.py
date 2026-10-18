"""Orca 2.5 alpha adapter. Core remains usable without Orca."""
from .adapter import AnalysisPipeline, ShowAnalysis
import orca


@orca.plugin
class QualityAnalysis(orca.base):
    def register_capabilities(self):
        orca.register_capability(AnalysisPipeline)
        orca.register_capability(ShowAnalysis)
