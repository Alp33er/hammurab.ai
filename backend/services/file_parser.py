"""
Dosya parse servisi — PDF, DOCX, TXT, UDF + OCR desteği.
Güvenlik: Memory-only işleme, diske yazılmaz.
"""

import io
import zipfile
import xml.etree.ElementTree as ET
from PyPDF2 import PdfReader

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import pytesseract
    from pdf2image import convert_from_bytes
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".udf"}


class FileParseError(Exception):
    pass


def validate_file(filename: str, content_type: str, size: int) -> str:
    if size > MAX_FILE_SIZE:
        raise FileParseError(f"Dosya çok büyük: {size / 1024 / 1024:.1f} MB (max 10 MB)")
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise FileParseError(f"Desteklenmeyen dosya türü: {ext} (izin verilen: PDF, DOCX, TXT, UDF)")
    return ext.lstrip(".")


def parse_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        if not text.strip():
            if HAS_OCR:
                return parse_pdf_ocr(data)
            raise FileParseError("PDF'den metin çıkarılamadı. Taranmış PDF ise OCR desteği gerekli.")
        return text.strip()
    except FileParseError:
        raise
    except Exception as e:
        raise FileParseError(f"PDF parse hatası: {e}")


def parse_pdf_ocr(data: bytes) -> str:
    if not HAS_OCR:
        raise FileParseError("OCR desteği yok: pip install pytesseract pdf2image")
    try:
        images = convert_from_bytes(data, dpi=300)
        text = ""
        for i, img in enumerate(images):
            page_text = pytesseract.image_to_string(img, lang="tur+eng")
            if page_text.strip():
                text += f"--- Sayfa {i+1} ---\n{page_text.strip()}\n\n"
        if not text.strip():
            raise FileParseError("OCR ile metin çıkarılamadı")
        return text.strip()
    except FileParseError:
        raise
    except Exception as e:
        raise FileParseError(f"OCR hatası: {e}")


def parse_udf(data: bytes) -> str:
    """UYAP UDF dosyasından metin çıkar (memory-only).

    UDF = ZIP arşivi içinde content.xml.
    content.xml'deki <content> CDATA bloğu tüm metni içerir.
    Elementler startOffset + length ile bu havuza referans verir.
    """
    try:
        # UDF bir ZIP arşivi
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                # content.xml'i bul
                xml_names = [n for n in z.namelist() if n.lower().endswith('.xml')]
                if 'content.xml' in z.namelist():
                    xml_data = z.read('content.xml').decode('utf-8')
                elif xml_names:
                    xml_data = z.read(xml_names[0]).decode('utf-8')
                else:
                    raise FileParseError("UDF arşivinde XML dosyası bulunamadı")
        except zipfile.BadZipFile:
            # Bazı UDF dosyaları doğrudan XML olabiliyor (ZIP olmadan)
            try:
                xml_data = data.decode('utf-8')
            except UnicodeDecodeError:
                xml_data = data.decode('windows-1254')

        # XML parse et
        root = ET.fromstring(xml_data)

        # <content> CDATA bloğunu bul — tüm metin burada
        content_elem = root.find('content')
        if content_elem is not None and content_elem.text:
            content_text = content_elem.text
        else:
            content_text = ""

        if content_text.strip():
            # Elementleri kullanarak yapılandırılmış metin oluştur
            elements = root.find('elements')
            if elements is not None:
                structured_text = _extract_udf_structured(content_text, elements)
                if structured_text.strip():
                    return structured_text.strip()
            # Fallback: düz metin
            return content_text.strip()

        # content CDATA boşsa, tüm text node'ları topla
        all_text = []
        for elem in root.iter():
            if elem.text and elem.text.strip():
                all_text.append(elem.text.strip())
            if elem.tail and elem.tail.strip():
                all_text.append(elem.tail.strip())

        text = "\n".join(all_text)
        if not text.strip():
            raise FileParseError("UDF dosyasından metin çıkarılamadı")
        return text.strip()

    except FileParseError:
        raise
    except ET.ParseError as e:
        raise FileParseError(f"UDF XML parse hatası: {e}")
    except Exception as e:
        raise FileParseError(f"UDF parse hatası: {e}")


def _extract_udf_structured(content_text: str, elements) -> str:
    """UDF elementlerinden yapılandırılmış metin çıkar."""
    lines = []
    for elem in elements:
        if elem.tag == 'paragraph':
            para_text = ""
            for child in elem:
                if child.tag == 'content':
                    start = int(child.get('startOffset', '0'))
                    length = int(child.get('length', '0'))
                    if start >= 0 and length > 0 and start + length <= len(content_text):
                        para_text += content_text[start:start + length]
                elif child.tag == 'tab':
                    para_text += "\t"
                elif child.tag == 'lineBreak':
                    para_text += "\n"
            if para_text.strip():
                lines.append(para_text)
        elif elem.tag == 'table':
            # Tablo satırlarını düz metin olarak çıkar
            for row in elem.findall('.//row'):
                row_cells = []
                for cell in row.findall('cell'):
                    cell_text = ""
                    for para in cell.findall('.//paragraph'):
                        for child in para:
                            if child.tag == 'content':
                                start = int(child.get('startOffset', '0'))
                                length = int(child.get('length', '0'))
                                if start >= 0 and length > 0 and start + length <= len(content_text):
                                    cell_text += content_text[start:start + length]
                    row_cells.append(cell_text.strip())
                if any(c for c in row_cells):
                    lines.append(" | ".join(row_cells))
        elif elem.tag == 'pageBreak':
            lines.append("\n--- Sayfa Sonu ---\n")
    return "\n".join(lines)


def parse_docx(data: bytes) -> str:
    if not HAS_DOCX:
        raise FileParseError("DOCX desteği yok: pip install python-docx")
    try:
        doc = docx.Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        if not text.strip():
            raise FileParseError("DOCX'ten metin çıkarılamadı")
        return text.strip()
    except FileParseError:
        raise
    except Exception as e:
        raise FileParseError(f"DOCX parse hatası: {e}")


def parse_txt(data: bytes) -> str:
    for encoding in ["utf-8", "windows-1254", "latin-1"]:
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    raise FileParseError("Dosya kodlaması tanınamadı")


def parse_file(data: bytes, file_type: str) -> str:
    parsers = {
        "pdf": parse_pdf,
        "docx": parse_docx,
        "txt": parse_txt,
        "udf": parse_udf,
    }
    parser = parsers.get(file_type)
    if not parser:
        raise FileParseError(f"Desteklenmeyen tür: {file_type}")
    return parser(data)
