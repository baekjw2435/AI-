# 보호막 계산 예시 (모두 shield_verify.py 통과, verified: true)

| 질문 | 결과 | 근거 | 증명서 |
|---|---|---|---|
| 보호막 1에서 ~칩 제시 | 제시한 쪽 패 | 상대 칩튠(한방) | present_칩_1.json |
| 보호막 2에서 ~칩 제시 | 제시한 쪽 승 | 칩튠이 막혀 응수 14가지 모두 짐 | present_칩_2.json |
| 보호막 3에서 ~칩 제시 | 제시한 쪽 승 | 칩샷엔 샷~션 | present_칩_3.json |
| 보호막 5에서 ~칩 제시 | 제시한 쪽 승 | | present_칩_5.json |
| 보호막 8에서 ~칩 제시 | 제시한 쪽 패 | 상대 칩샷 → 보호막 6의 샷에서 션이 막힘 | present_칩_8.json |
| 보호막 12에서 ~칩 제시 | 미확정 | 시간 한도 30분 안에 못 끝냄 | 없음 |
| 보호막 3에서 죄를 받음 | 받은 쪽 승 | 이기는 수는 죄칩 하나뿐(나머지 95가지 짐) | receive_죄_3.json |
| 보호막 4에서 ~척 제시 | 제시한 쪽 패 | 상대 척척박사상급(→급) | present_척_4.json |
| 보호막 2에서 ~듯 제시 | 제시한 쪽 승 | | present_듯_2.json |
| 보호막 5에서 ~션 제시 | 제시한 쪽 승 | | present_션_5.json |
| 보호막 1에서 ~놈 제시 | 제시한 쪽 패 | 상대 놈놈놈 | present_놈_1.json |
| 보호막 6에서 균을 받음 | 받은 쪽 승 | 균핵꼬리버섯(→섯) | receive_균_6.json |

`.txt`는 계산기 출력, `.json.route/`는 쓴 루트 단어가 있는 루트 자리의 solver_v5 증명서(verify_v4 수락).
다시 확인: `python3 eoinjeong_root/shield/shield_verify.py eoinjeong_root/shield/examples/present_칩_8.json`
