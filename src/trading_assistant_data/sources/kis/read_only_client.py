"""Read-only Korea Investment & Securities quotation/history client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


READ_ONLY_TR_IDS = {
    "FHKST01010100",  # current price
    "FHKST01010200",  # orderbook quote
    "FHKST03010100",  # daily chart
    "FHKST03010200",  # minute chart
    "FHKST01010900",  # investor trend
    "FHPST01710000",  # volume ranking
    "FHPST01700000",  # fluctuation ranking
    "HHKST03900400",  # condition search
}


@dataclass(frozen=True)
class KisReadOnlyClient:
    base_url: str
    app_key: str
    app_secret: str
    access_token: str
    timeout_seconds: int = 20

    def get_current_price(self, symbol: str) -> dict[str, Any]:
        return self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol},
        )

    def get_orderbook_quote(self, symbol: str) -> dict[str, Any]:
        return self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
            "FHKST01010200",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol},
        )

    def get_daily_chart(self, symbol: str, start_yyyymmdd: str, end_yyyymmdd: str) -> dict[str, Any]:
        return self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100",
            {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": symbol,
                "fid_input_date_1": start_yyyymmdd,
                "fid_input_date_2": end_yyyymmdd,
                "fid_period_div_code": "D",
                "fid_org_adj_prc": "1",
            },
        )

    def get_minute_chart(self, symbol: str, minute: int = 1) -> dict[str, Any]:
        return self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            "FHKST03010200",
            {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": symbol,
                "fid_pw_data_incu_yn": "Y",
                "fid_etc_cls_code": "",
                "fid_input_hour_1": "",
                "fid_period_div_code": str(minute),
            },
        )

    def get_investor_trend(self, symbol: str) -> dict[str, Any]:
        return self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            "FHKST01010900",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol},
        )

    def get_volume_ranking(self, market: str = "KOSPI", limit: int = 30) -> dict[str, Any]:
        return self._get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            "FHPST01710000",
            {
                "fid_cond_mrkt_div_code": "J" if market.upper() == "KOSPI" else "Q",
                "fid_cond_scr_div_code": "20171",
                "fid_input_iscd": "0000",
                "fid_input_cnt_1": str(limit),
            },
        )

    def get_condition_search(self, condition_id: str, hts_id: str) -> dict[str, Any]:
        return self._get(
            "/uapi/domestic-stock/v1/quotations/psearch-result",
            "HHKST03900400",
            {"user_id": hts_id, "seq": condition_id},
        )

    def _get(self, path: str, tr_id: str, params: dict[str, Any]) -> dict[str, Any]:
        if tr_id not in READ_ONLY_TR_IDS:
            raise ValueError(f"TR_ID is not approved for read-only use: {tr_id}")
        headers = {
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        response = requests.get(
            f"{self.base_url.rstrip('/')}{path}",
            headers=headers,
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("KIS response was not a JSON object")
        return data

