"""Shared native world adapter; session lifecycle/receipts use the sheet gateway."""
import importlib.util
import math
from pathlib import Path
spec = importlib.util.spec_from_file_location('native_sheet_sessions', Path(__file__).with_name('sheet-world.py'))
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)

class DropManager(shared.SheetManager):
    observation_limit = 3002
    advance_steps = 4

    def __init__(self, native, log_root=None):
        super().__init__(native, log_root or Path(__file__).resolve().parents[1] / 'build/drop-world-logs')

    def validate_create(self, request):
        if set(request) != {'op','sheet','ball','mass_kg','height_m','offset_m','mode','speed_m_s'}:
            raise ValueError('Invalid drop declaration')
        if request['sheet'] not in shared.MATERIALS or request['ball'] not in shared.MATERIALS:
            raise ValueError('Unknown material')
        if request['mode'] not in ('rigid','deformable'): raise ValueError('Unknown world mode')
        for key, lower, upper in (('mass_kg',.1,5),('height_m',0,10),('offset_m',-.08,.08),('speed_m_s',0,15)):
            value=request[key]
            if type(value) not in (float,int) or not math.isfinite(value) or not lower<=value<=upper:
                raise ValueError('Drop value outside admitted bounds')
        return dict(request)
