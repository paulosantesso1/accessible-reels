"""Executor e organizador unificado da suíte de testes do Accessible Reels.

Permite rodar as verificações:
  - Separadas: Executa cada arquivo de teste isoladamente.
  - Unidas: Executa a suíte completa de forma integrada.
  - Ambas (padrão): Roda primeiro arquivo por arquivo e depois a suíte unida.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
TESTS_DIR = ROOT / "tests"
PYTHON = sys.executable


def get_test_files() -> list[Path]:
    """Retorna todos os arquivos de teste ordenados."""
    return sorted(TESTS_DIR.glob("test_*.py"))


def run_command(args: list[str]) -> tuple[int, str]:
    """Executa um comando e retorna o código de saída e a saída combinada."""
    result = subprocess.run(
        args,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout


def run_separated(files: list[Path]) -> bool:
    """Executa cada arquivo de teste individualmente (verificação separada)."""
    print("=" * 70)
    print("INICIANDO VERIFICAÇÃO SEPARADA (ARQUIVO POR ARQUIVO)")
    print("=" * 70)

    total_files = len(files)
    all_ok = True
    results: list[tuple[str, bool, str, float]] = []

    start_all = time.time()
    for idx, test_file in enumerate(files, 1):
        rel_path = test_file.relative_to(ROOT)
        t0 = time.time()
        code, output = run_command([PYTHON, "-m", "pytest", str(rel_path), "-q"])
        elapsed = time.time() - t0
        ok = (code == 0)
        if not ok:
            all_ok = False
        summary_line = output.strip().splitlines()[-1] if output.strip() else ""
        results.append((test_file.name, ok, summary_line, elapsed))
        status = "PASS" if ok else "FAIL"
        print(f"[{idx:02d}/{total_files:02d}] {status} ({elapsed:5.2f}s) - {test_file.name}: {summary_line}", flush=True)

    elapsed_all = time.time() - start_all
    print("-" * 70)
    passed_count = sum(1 for _, ok, _, _ in results if ok)
    failed_count = total_files - passed_count
    print(f"Resultado Separado: {passed_count}/{total_files} arquivos passaram em {elapsed_all:.1f}s.")
    if failed_count > 0:
        print(f"FALHAS: {failed_count} arquivos falharam!")
    print("=" * 70)
    return all_ok


def run_united() -> bool:
    """Executa todos os testes juntos em uma única sessão (verificação unida)."""
    print("\n" + "=" * 70)
    print("INICIANDO VERIFICAÇÃO UNIDA (SUÍTE COMPLETA)")
    print("=" * 70)

    t0 = time.time()
    code, output = run_command([PYTHON, "-m", "pytest", "tests", "-q"])
    elapsed = time.time() - t0

    print(output)
    print("-" * 70)
    ok = (code == 0)
    status = "SUCESSO (PASS)" if ok else "FALHA (FAIL)"
    print(f"Resultado Unido: {status} em {elapsed:.1f}s")
    print("=" * 70)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Organizador e executor da suíte de testes")
    parser.add_argument(
        "--mode",
        choices=["separated", "united", "both"],
        default="both",
        help="Modo de execução: separated, united ou both (padrão: both)",
    )
    args = parser.parse_args()

    test_files = get_test_files()
    if not test_files:
        print("Nenhum arquivo de teste encontrado em tests/test_*.py!")
        return 1

    print(f"Accessible Reels - Suíte de Testes")
    print(f"Arquivos catalogados: {len(test_files)}")
    print(f"Interpretador Python: {PYTHON}\n")

    separated_ok = True
    united_ok = True

    if args.mode in ("separated", "both"):
        separated_ok = run_separated(test_files)

    if args.mode in ("united", "both"):
        united_ok = run_united()

    if separated_ok and united_ok:
        print("\n>>> TODAS AS VERIFICAÇÕES (SEPARADAS E UNIDAS) PASSARAM COM 100% DE SUCESSO! <<<")
        return 0
    else:
        print("\n>>> OCORRERAM FALHAS NAS VERIFICAÇÕES! <<<")
        return 1


if __name__ == "__main__":
    sys.exit(main())
