#!/usr/bin/env python3
"""보호막 도구가 읽는 자료(어느 게임인가).

환경 변수 SHIELD_GAME
  end   (기본) 끝말잇기: 이 폴더의 source/(어인정 표준사전 482,556단어, 공격 목록), eoinjeong_root/words_621.txt,
        eoinjeong_root/site/data.json(루트 확정 결과). 지금까지와 똑같다.
  front 앞말잇기: apmal_root/의 '뒤집은' 자료(표준사전 291,652단어, 루트 단어 534개, 공격 목록)와
        apmal_root/site/data.json(앞말잇기 루트 확정 결과). 단어를 모두 뒤집으면 앞말잇기 = 끝말잇기라서
        계산·검증 규칙은 그대로이고, 화면에 낼 때만 단어를 다시 뒤집는다(show).

모형 파일(C 엔진 입력)은 게임마다 다른 폴더(MODEL_DIR)에 둔다. 컴파일한 실행 파일(BIN)은 같이 쓴다.
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent          # eoinjeong_root/shield
ROOT = HERE.parent                              # eoinjeong_root
REPO = ROOT.parent
BIN = HERE / 'bin'                              # shield_engine, solver_v5, verify_v4 (게임과 무관)

GAME = os.environ.get('SHIELD_GAME', 'end')
if GAME == 'end':
    DICT = HERE / 'source' / '표준사전_어인정_전체단어.txt'
    ATTACK = HERE / 'source' / '공격단어_목록.txt'
    ROUTE_WORDS = ROOT / 'words_621.txt'
    N_ROUTE = 621
    ROUTE_DATA = ROOT / 'site' / 'data.json'
    MODEL_DIR = BIN
    TABLE_DIR = HERE
elif GAME == 'front':
    FRONT = REPO / 'apmal_root'
    DICT = FRONT / 'reversed' / '표준사전_뒤집음.txt'
    ATTACK = FRONT / 'reversed' / '공격단어_뒤집음.txt'
    ROUTE_WORDS = FRONT / 'words_534.txt'
    N_ROUTE = 534
    ROUTE_DATA = FRONT / 'site' / 'data.json'
    MODEL_DIR = FRONT / 'shield' / 'bin'
    TABLE_DIR = FRONT / 'shield'
else:
    raise SystemExit(f'SHIELD_GAME은 end(끝말잇기) 또는 front(앞말잇기): {GAME!r}')

# 화면 문구: 끝말잇기는 '이 음절로 시작하는 단어', 앞말잇기는 '이 음절로 끝나는 단어'가 이을 수 있는 단어다.
CONT_WORD = '시작하는' if GAME == 'end' else '끝나는'
GAME_NAME = '끝말잇기' if GAME == 'end' else '앞말잇기'


def show(word):
    """화면·표에 낼 단어. 앞말잇기 자료는 뒤집혀 있으므로 다시 뒤집는다(음절 하나는 그대로)."""
    return word[::-1] if GAME == 'front' else word


def show_why(why):
    """계산기 근거 문구 속 단어('단어(→음절)')만 화면용으로 바꾼다."""
    if GAME != 'front' or not why:
        return why
    import re
    m = re.match(r'^(\S+)\(→(.)\)$', why)
    return f'{show(m.group(1))}(→{m.group(2)})' if m else why
