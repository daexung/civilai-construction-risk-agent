"""KMA API 예외 클래스 (T4)"""


class KmaApiError(Exception):
    """기본 예외. resultCode와 resultMsg를 보관."""

    def __init__(self, message: str, result_code: str | None = None, result_msg: str | None = None):
        super().__init__(message)
        self.result_code = result_code
        self.result_msg = result_msg


class KmaNoDataError(KmaApiError):
    """resultCode "03" — 아직 생성되지 않은 발표자료. 이전 base_time으로 fallback."""


class KmaAuthenticationError(KmaApiError):
    """resultCode "20","21","30","32","33" — 인증 오류. 재시도 불필요."""


class KmaInvalidParameterError(KmaApiError):
    """resultCode "10","11" — 파라미터 오류. 재시도 불필요."""


class KmaRateLimitError(KmaApiError):
    """resultCode "22" — 호출 한도 초과. 즉시 실패."""


class KmaServerError(KmaApiError):
    """resultCode "01","02","04","05","99" 또는 HTTP 5xx — 서버 오류. 재시도 가능."""


class KmaResponseFormatError(KmaApiError):
    """JSON 파싱 실패 또는 필수 필드 누락. 재시도 불필요."""
