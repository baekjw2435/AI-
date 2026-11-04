#!/bin/sh
# run from the repository root
python3 guopsaem_root/verifier_v4/verify_v4.py --dictionary guopsaem_root/verifier_v4/attacks/cases/crlf_lines/d.txt --expected-word-count 0 --position guopsaem_root/verifier_v4/attacks/cases/crlf_lines/p.json --proof guopsaem_root/verifier_v4/attacks/cases/crlf_lines/proof.jsonl
guopsaem_root/verifier_v4/build/verify_v4 --dictionary guopsaem_root/verifier_v4/attacks/cases/crlf_lines/d.txt --expected-word-count 0 --position guopsaem_root/verifier_v4/attacks/cases/crlf_lines/p.json --proof guopsaem_root/verifier_v4/attacks/cases/crlf_lines/proof.jsonl
python3 guopsaem_root/verifier_v4/verify_v4.py --dictionary guopsaem_root/verifier_v4/attacks/cases/crlf_lines/d.txt --expected-word-count 0 --position guopsaem_root/verifier_v4/attacks/cases/crlf_lines/p.json --proof guopsaem_root/verifier_v4/attacks/cases/crlf_lines/proof.jsonl --digest-only
guopsaem_root/verifier_v4/build/verify_v4 --dictionary guopsaem_root/verifier_v4/attacks/cases/crlf_lines/d.txt --expected-word-count 0 --position guopsaem_root/verifier_v4/attacks/cases/crlf_lines/p.json --proof guopsaem_root/verifier_v4/attacks/cases/crlf_lines/proof.jsonl --digest-only
