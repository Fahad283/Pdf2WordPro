"""Self-issued test signature and deliberately invalid benchmark fixtures."""

from datetime import UTC, datetime
import re

import pymupdf as fitz

BYTE_RANGE = re.compile(rb"/ByteRange\s*\[\s*0\s+1111111111\s+2222222222\s+3333333333\s*\]")
CONTENTS = re.compile(rb"/Contents\s*(<0{8192,}>)")
SIGNATURE_HEX_CAPACITY = 16_384


def empty_pdf() -> bytes:
    """A syntactically complete PDF whose page tree is empty."""
    data = bytearray(b"%PDF-1.7\n")
    objects = (b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Count 0 /Kids [] >>")
    offsets = []
    for number, value in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(value + b"\nendobj\n")
    xref = len(data)
    data.extend(b"xref\n0 3\n0000000000 65535 f \n")
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def sign_pdf(document: fitz.Document) -> bytes:
    """Create a real detached CMS signature with an ephemeral test-only certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs7
    from cryptography.x509.oid import NameOID

    widgets = document[0].widgets(types=(fitz.PDF_WIDGET_TYPE_SIGNATURE,))
    widget = next(widgets)
    signature = document.get_new_xref()
    placeholder = "0" * SIGNATURE_HEX_CAPACITY
    document.update_object(
        signature,
        f"<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached "
        f"/ByteRange [0 1111111111 2222222222 3333333333] /Contents <{placeholder}> "
        "/M (D:20260101000000Z) /Name (Blue Harbor Synthetic QA) >>",
    )
    document.xref_set_key(widget.xref, "V", f"{signature} 0 R")
    document.xref_set_key(document.pdf_catalog(), "AcroForm/SigFlags", "3")
    pdf = document.tobytes(no_new_id=True, use_objstms=0)
    range_match, content_match = BYTE_RANGE.search(pdf), CONTENTS.search(pdf)
    if not range_match or not content_match:
        raise RuntimeError("The PDF serializer did not preserve the signature placeholders.")
    start, end = content_match.span(1)
    replacement = f"/ByteRange [0 {start:d} {end:d} {len(pdf) - end:d}]".encode()
    if len(replacement) > len(range_match[0]):
        raise RuntimeError("The signature byte ranges exceed the reserved space.")
    signed = pdf[:range_match.start()] + replacement.ljust(len(range_match[0])) + pdf[range_match.end():]
    key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Blue Harbor Synthetic QA")])
    certificate = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(datetime(2026, 1, 1, tzinfo=UTC)).not_valid_after(datetime(2046, 1, 1, tzinfo=UTC))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cms = (
        pkcs7.PKCS7SignatureBuilder().set_data(signed[:start] + signed[end:])
        .add_signer(certificate, key, hashes.SHA256()).sign(
            serialization.Encoding.DER,
            [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary, pkcs7.PKCS7Options.NoAttributes],
        )
    )
    encoded = cms.hex().encode()
    if len(encoded) > SIGNATURE_HEX_CAPACITY:
        raise RuntimeError("The CMS test signature exceeds its reserved PDF field.")
    return signed[:start + 1] + encoded.ljust(SIGNATURE_HEX_CAPACITY, b"0") + signed[end - 1:]
