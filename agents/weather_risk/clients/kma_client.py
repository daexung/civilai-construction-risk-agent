"""
KmaClient — 기상청 Open API HTTP 클라이언트 (T4)

재시도 정책:
  retryable  : httpx.TimeoutException, httpx.ConnectError, HTTP 5xx, KmaServerError
  immediate  : KmaNoDataError, KmaAuthenticationError, KmaInvalidParameterError,
               KmaRateLimitError, KmaResponseFormatError

NO_DATA fallback:
  KmaNoDataError 발생 시 이전 base_time으로 자동 소급 (max_no_data_fallbacks 횟수까지).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import NamedTuple

import httpx
from dotenv import load_dotenv

_log = logging.getLogger(__name__)

from weather_risk.models import ForecastSource, KST
from weather_risk.resolvers.base_time_resolver import BaseTime, BaseTimeResolver
from weather_risk.clients.exceptions import (
    KmaApiError,
    KmaAuthenticationError,
    KmaInvalidParameterError,
    KmaNoDataError,
    KmaRateLimitError,
    KmaResponseFormatError,
    KmaServerError,
)

_DEFAULT_VILAGE_FCST_URL = (
    "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
)
_DEFAULT_ULTRA_SRT_NCST_URL = (
    "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
)

def _auth_param_name(url: str) -> str:
    """URL 호스트에 따른 인증 파라미터명을 반환한다.

    - apihub.kma.go.kr  → 'authKey'
    - apis.data.go.kr   → 'serviceKey'
    """
    return "authKey" if "apihub.kma.go.kr" in url else "serviceKey"


RESULT_CODE_MAP: dict[str, type[KmaApiError] | None] = {
    "00": None,
    "03": KmaNoDataError,
    "01": KmaServerError,
    "02": KmaServerError,
    "04": KmaServerError,
    "05": KmaServerError,
    "99": KmaServerError,
    "10": KmaInvalidParameterError,
    "11": KmaInvalidParameterError,
    "20": KmaAuthenticationError,
    "21": KmaAuthenticationError,
    "30": KmaAuthenticationError,
    "32": KmaAuthenticationError,
    "33": KmaAuthenticationError,
    "22": KmaRateLimitError,
}


class KmaFetchResult(NamedTuple):
    source: ForecastSource
    items: list[dict]
    base_time: BaseTime       # fallback 적용 후 실제로 성공한 base_time
    fetched_at: datetime      # 호출 완료 시각 (KST)


class KmaClient:
    def __init__(
        self,
        api_key: str | None = None,
        vilage_fcst_url: str | None = None,
        ultra_srt_ncst_url: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ):
        load_dotenv()
        self._api_key = api_key or os.environ.get("KMA_API_KEY")
        if not self._api_key:
            raise ValueError(
                "KMA_API_KEY is required. "
                "Pass api_key= argument or set KMA_API_KEY environment variable."
            )
        self._vilage_fcst_url = (
            vilage_fcst_url
            or os.environ.get("KMA_VILAGE_FCST_URL", _DEFAULT_VILAGE_FCST_URL)
        )
        self._ultra_srt_ncst_url = (
            ultra_srt_ncst_url
            or os.environ.get("KMA_ULTRA_SRT_NCST_URL", _DEFAULT_ULTRA_SRT_NCST_URL)
        )
        self._timeout = timeout
        self._max_retries = max_retries
        self._transport = transport

    # ─────────────────────── public API ───────────────────────────

    def fetch_vilage_fcst(
        self,
        nx: int,
        ny: int,
        now: datetime,
        max_no_data_fallbacks: int = 3,
    ) -> KmaFetchResult:
        return self._fetch(
            source=ForecastSource.VILAGE_FCST,
            url=self._vilage_fcst_url,
            nx=nx,
            ny=ny,
            now=now,
            max_no_data_fallbacks=max_no_data_fallbacks,
        )

    def fetch_ultra_srt_ncst(
        self,
        nx: int,
        ny: int,
        now: datetime,
        max_no_data_fallbacks: int = 3,
    ) -> KmaFetchResult:
        return self._fetch(
            source=ForecastSource.ULTRA_SRT_NCST,
            url=self._ultra_srt_ncst_url,
            nx=nx,
            ny=ny,
            now=now,
            max_no_data_fallbacks=max_no_data_fallbacks,
        )

    # ─────────────────────── internal ─────────────────────────────

    def _fetch(
        self,
        source: ForecastSource,
        url: str,
        nx: int,
        ny: int,
        now: datetime,
        max_no_data_fallbacks: int,
    ) -> KmaFetchResult:
        resolver = BaseTimeResolver()
        current_now = now  # naive → ValueError from resolver, propagated as-is

        for attempt in range(max_no_data_fallbacks):
            base_time = resolver.resolve(source, current_now)
            try:
                items = self._request(
                    url,
                    {
                        _auth_param_name(url): self._api_key,
                        "pageNo": 1,
                        "numOfRows": 1000,
                        "dataType": "JSON",
                        "base_date": base_time.base_date,
                        "base_time": base_time.base_time,
                        "nx": nx,
                        "ny": ny,
                    },
                )
                return KmaFetchResult(
                    source=source,
                    items=items,
                    base_time=base_time,
                    fetched_at=datetime.now(KST),
                )
            except KmaNoDataError:
                if attempt == max_no_data_fallbacks - 1:
                    raise
                current_now = base_time.as_datetime() - timedelta(minutes=1)

        raise RuntimeError("unreachable")  # max_no_data_fallbacks >= 1 보장

    def _request(self, url: str, params: dict) -> list[dict]:
        """GET 요청 with 재시도. 성공 시 response.body.items.item 리스트 반환."""
        _auth_param = "authKey" if "authKey" in params else "serviceKey"
        _key = params.get(_auth_param, "")
        _masked = f"{_key[:4]}...{_key[-4:]}" if len(_key) > 8 else "****"
        print(
            f'[KMA 요청] endpoint={url}'
            f'  base_date={params.get("base_date")}'
            f'  base_time={params.get("base_time")}'
            f'  nx={params.get("nx")}  ny={params.get("ny")}'
            f'  {_auth_param}={_masked}'
        )
        for attempt in range(self._max_retries + 1):
            try:
                with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                    resp = client.get(url, params=params)

                print(f'[KMA 응답] HTTP_status={resp.status_code}')
                if resp.status_code >= 500:
                    # KMA 서버 에러 본문(원인 진단용)을 로깅한다. 보통 117바이트 내외의
                    # JSON으로 무효 authKey / 데이터 없음 등의 사유가 들어 있다.
                    _log.warning(
                        "KMA HTTP %s — url=%s params=%s body=%s",
                        resp.status_code, url, params, resp.text[:500],
                    )
                    raise KmaServerError(f"HTTP {resp.status_code}: {resp.text[:300]}")

                try:
                    data = resp.json()
                except Exception as exc:
                    _log.warning("KMA JSON 파싱 실패 — body=%s", resp.text[:500])
                    raise KmaResponseFormatError(f"JSON parse error: {exc}") from exc

                try:
                    header = data["response"]["header"]
                    result_code = header["resultCode"]
                    result_msg = header.get("resultMsg", "")
                except (KeyError, TypeError) as exc:
                    raise KmaResponseFormatError(
                        f"Missing response.header.resultCode: {exc}"
                    ) from exc

                print(f'[KMA 응답] resultCode={result_code}  resultMsg={result_msg!r}')
                exc_class = RESULT_CODE_MAP.get(result_code)
                if exc_class is not None:
                    raise exc_class(
                        f"KMA error {result_code}: {result_msg}",
                        result_code=result_code,
                        result_msg=result_msg,
                    )

                try:
                    items = data["response"]["body"]["items"]["item"]
                    if not isinstance(items, list):
                        items = [items]
                except (KeyError, TypeError) as exc:
                    raise KmaResponseFormatError(
                        f"Missing response.body.items.item: {exc}"
                    ) from exc

                print(f'[KMA 응답] items 개수={len(items)}')
                return items

            except (httpx.TimeoutException, httpx.ConnectError, KmaServerError) as exc:
                print(f'[KMA 예외] type={type(exc).__name__}  msg={exc}  attempt={attempt + 1}/{self._max_retries + 1}')
                if attempt == self._max_retries:
                    raise  # 재시도 소진 — 마지막 예외 그대로 전파
                # else: 다음 attempt로

            except KmaApiError as exc:
                print(f'[KMA 예외] type={type(exc).__name__}  msg={exc}')
                raise  # non-retryable, 즉시 전파

        raise RuntimeError("unreachable")
