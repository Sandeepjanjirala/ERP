from rest_framework import renderers


class FileRenderer(renderers.BaseRenderer):
    """Lets clients ask for a file type. Success responses are already the file; errors (dicts)
    become their plain-text message."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return str(data.get("detail", data) if isinstance(data, dict) else data).encode()


class CSVRenderer(FileRenderer):
    media_type = "text/csv"
    format = "csv"


class PDFRenderer(FileRenderer):
    media_type = "application/pdf"
    format = "pdf"
