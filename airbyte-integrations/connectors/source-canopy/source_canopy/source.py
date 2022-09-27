#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#
from __future__ import annotations

from abc import ABC, abstractmethod
from multiprocessing import AuthenticationError
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple, Type

import requests
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream, HttpSubStream
from airbyte_cdk.models import SyncMode
from airbyte_cdk.sources.streams.http.auth import TokenAuthenticator


# Basic full refresh stream
class CanopyStream(HttpStream, ABC):

    url_base = "https://tandym-api.us.canopyservicing.com/"

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        paging_data = response.json()["paging"]
        next_page_token = paging_data.get("has_more")

        if next_page_token:
            next_page_starting_after = paging_data.get("starting_after")
            return {"starting_after": next_page_starting_after}
        else:
            return None

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json["results"]

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        
        params = super().request_params(stream_state=stream_state, next_page_token=next_page_token, **kwargs)
        params["limit"] = 100

        if next_page_token:
            params.update(**next_page_token)
        return params
class Customers(CanopyStream):

    primary_key = "customer_id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "customers"
class Accounts(CanopyStream):

    primary_key = "account_id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "customers/accounts"
class AccountRelatedStream(CanopyStream, ABC):    
    
    def stream_slices(
        self, sync_mode: SyncMode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        accounts_stream = Accounts(authenticator=self.authenticator)
        for record in accounts_stream.read_records(sync_mode=SyncMode.full_refresh):
            yield {"account_id": record["account"]["account_id"]}
class LineItems(AccountRelatedStream):

    primary_key = "line_item_id"

    def path(self, stream_slice: Mapping[str, Any] = None, **kwargs) -> str:
        account_id = stream_slice["account_id"]
        return f"accounts/{account_id}/line_items"
class StatementsList(AccountRelatedStream):

    primary_key = "statement_id"

    def path(self, stream_slice: Mapping[str, Any] = None, **kwargs) -> str:
        account_id = stream_slice["account_id"]
        return f"accounts/{account_id}/statements/list"

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        for record in response.json():
            yield record

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        return None
class StatementRelatedStream(StatementsList, ABC):    
    
    def stream_slices(
        self, sync_mode: SyncMode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        statements_stream = StatementsList(authenticator=self.authenticator)
        for record in statements_stream.read_records(sync_mode=SyncMode.full_refresh):
            yield {"account_id": record["account_id"],"statement_id":record["statement_id"]}
class StatementsDetail(StatementRelatedStream):

    primary_key = "statement_id"

    def path(self, stream_slice: Mapping[str, Any] = None, **kwargs) -> str:
        account_id = stream_slice["account_id"]
        statement_id = stream_slice["statement_id"]
        return f"accounts/{account_id}/statements/{statement_id}"

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        for record in response.json():
            yield record

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        return None
# Source
class SourceCanopy(AbstractSource):
   
    @staticmethod
    def _get_authenticator(config: dict):
        
        url = 'https://tandym-api.us.canopyservicing.com/auth/token'
        post_obj = {'client_id': config.get("client_id", None), 'client_secret': config.get("client_secret", None)}
        
        auth_token = requests.post(url, json = post_obj).json()["access_token"]

        #auth_token = config.get("auth_token", None)
        if not auth_token:
            raise Exception("Config validation error: 'auth_token' is a required property")

        auth = TokenAuthenticator(token=auth_token)
        return auth
    
    def check_connection(self, logger, config) -> Tuple[bool, any]:
        try:
            auth = self._get_authenticator(config)
            stream = Customers(authenticator=auth)
            records = stream.read_records(sync_mode="full_refresh")
            record = next(records)
            logger.info(f"Successfully connected to Customers stream. Pulled one record: {record}")
            return True, None
        except requests.exceptions.RequestException as e:
            return False, e

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        args = {"authenticator": self._get_authenticator(config)}
        return [
            Customers(**args),
            Accounts(**args),
            LineItems(**args),
            StatementsList(**args),
            StatementsDetail(**args)]