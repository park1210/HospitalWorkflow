# -*- coding: utf-8 -*-
"""역할별 데이터 읽기와 정확한 source event 조회. 모델·확률·simulator 없음."""
from copy import deepcopy
import json
from pathlib import Path


class ReplayDataset:
    def __init__(self,folder,policy='snapshot'):
        self.folder = Path(folder)
        if (self.folder/'INCOMPLETE').exists():
            raise ValueError('미완료 데이터입니다.')
        if policy not in {'snapshot','recorded_time_proxy'}:
            raise ValueError('snapshot 또는 recorded_time_proxy를 지정하세요.')
        filename = 'cases.json' if policy=='snapshot' else 'cases_recorded_time_proxy.json'
        rows = json.loads((self.folder/filename).read_text(encoding='utf-8'))
        self.cases = {c['case_id']:c for c in rows}
        if len(self.cases)!=len(rows):
            raise ValueError('case ID 중복')
        self.patient_states = {}
        with (self.folder/'patient_states.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                self.patient_states[row['case_id']] = row

    def doctor_input(self,case_id):
        case = self.cases[case_id]
        initial = case['current_initial_state']
        # future Test 이름과 evidence, patient 전용 score, 평가/provenance는 공개하지 않는다.
        return {'case_id':case_id,'index_encounter':{
            'encounter_id':case['index_encounter_id'],'start_time':case['index_encounter_start']},
            'doctor_visible_info':deepcopy(initial['doctor_visible_info']),
            'initial_symptom_names':deepcopy(initial['patient_visible_info'].get('associated_symptoms',[]))}

    def patient_input(self,case_id):
        return deepcopy(self.patient_states[case_id])

    def memory_records(self,case_id):
        return [deepcopy(r) for v in self.cases[case_id]['past_visits'] for r in v['records']]

    def available_questions(self,case_id,minute=0):
        return [e['target'] for e in self.cases[case_id]['current_encounter_events']
                if e['action']=='Ask' and e['available_minute']<=minute]

    def source_evidence(self,case_id,action,target,minute=0):
        """신뢰된 environment 전용. 요청한 정확한 source만 반환하고 없는 답은 None."""
        if action not in {'Ask','Test','Consult'}:
            raise ValueError('지원하지 않는 action')
        for e in self.cases[case_id]['current_encounter_events']:
            if e['action']==action and e['target']==target and e['available_minute']<=minute:
                return deepcopy(e)
        return None
