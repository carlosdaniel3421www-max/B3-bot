"""Contrato de persistencia do workflow; sem Git remoto ou rede."""
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/relatorio.yml"


def test_concorrencia_e_checkout_branch_atual():
    texto = WORKFLOW.read_text(encoding="utf-8")
    assert "    concurrency:\n" in texto
    assert "group: relatorio-estado-${{ github.ref }}" in texto
    assert "cancel-in-progress: false" in texto
    assert "ref: ${{ github.ref_name }}" in texto


def test_commit_unico_e_guarda_arquivos():
    texto = WORKFLOW.read_text(encoding="utf-8")
    assert texto.count("git commit ") == 1
    assert texto.count("git push ") == 1
    assert 'GITHUB_TOKEN: ""' in texto
    assert "always() && steps.checkout.outcome == 'success'" in texto
    assert "for arquivo in estado.json sinais.json propostas.json; do" in texto
    ausente = texto.index('if [[ ! -f "$arquivo" ]]')
    rastreado = texto.index('git ls-files --error-unmatch -- "$arquivo"')
    ignorado = texto.index('git check-ignore -q -- "$arquivo"')
    assert ausente < rastreado < ignorado
    assert 'continue' in texto[ausente:rastreado]
    assert 'git add -- "$arquivo"' in texto[rastreado:ignorado]
    trecho_ignorado = texto[ignorado:texto.index("            else", ignorado)]
    assert "::warning::" in trecho_ignorado
    assert "git add" not in trecho_ignorado
    assert "git add -f" not in texto


def test_push_falha_explicitamente_sem_sobrescrever():
    texto = WORKFLOW.read_text(encoding="utf-8")
    assert 'if ! git push origin "HEAD:refs/heads/$BRANCH"; then' in texto
    trecho = texto[texto.index("if ! git push"):]
    assert "::error::" in trecho
    assert "exit 1" in trecho
    for comando in ("git pull", "git rebase", "git reset", "--force", "git checkout --"):
        assert comando not in texto
    assert "actions/upload-artifact@v4" in texto
    assert "if: ${{ failure() }}" in trecho
    assert "            estado.json\n            sinais.json\n            propostas.json" in trecho
