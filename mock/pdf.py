"""
Gerador de PDF mínimo, sem dependências (só para os documentos fictícios do mock).

Monta um PDF 1.4 válido de uma página com fonte Helvetica (WinAnsi), calculando
a tabela xref à mão. Suficiente para o navegador abrir e para o upload do robô.
"""
from __future__ import annotations


def _escapar(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def gerar_pdf(linhas: list[str], titulo: str = "Documento fictício") -> bytes:
    """Devolve os bytes de um PDF com `titulo` em destaque e as `linhas` abaixo."""
    partes = ["BT", "/F2 16 Tf", "72 770 Td", f"({_escapar(titulo)}) Tj", "/F1 11 Tf", "0 -28 Td", "15 TL"]
    for linha in linhas:
        partes.append(f"({_escapar(linha)}) Tj T*")
    partes += ["ET",
               # tarja de aviso no rodapé
               "BT /F2 9 Tf 72 60 Td (DOCUMENTO 100% FICTICIO - GERADO PELO MOCK DE DEMONSTRACAO) Tj ET"]
    conteudo = "\n".join(partes).encode("cp1252", errors="replace")

    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(conteudo)).encode() + b" >>\nstream\n" + conteudo + b"\nendstream",
    ]
    saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, obj in enumerate(objetos, 1):
        offsets.append(len(saida))
        saida += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    inicio_xref = len(saida)
    saida += f"xref\n0 {len(objetos) + 1}\n".encode()
    saida += b"0000000000 65535 f \n"
    for off in offsets:
        saida += f"{off:010d} 00000 n \n".encode()
    saida += (f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
              f"startxref\n{inicio_xref}\n%%EOF\n").encode()
    return bytes(saida)
