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
from airbyte_cdk.sources.streams.http import HttpStream
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

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        
        params = super().request_params(stream_state=stream_state, next_page_token=next_page_token, **kwargs)
        params["limit"] = 10

        if next_page_token:
            params.update(**next_page_token)
        return params

    def read_slices_from_records(self, stream_class: Type[CanopyStream], slice_field: str) -> Iterable[Optional[Mapping[str, Any]]]:
        """
        General function for getting parent stream (which should be passed through `stream_class`) slice.
        Generates dicts with `account_id` of parent streams.
        """
        stream = stream_class(authenticator=self.authenticator)
        stream_slices = stream.stream_slices(sync_mode=SyncMode.full_refresh)
        for stream_slice in stream_slices:
            for record in stream.read_records(sync_mode=SyncMode.full_refresh, stream_slice=stream_slice):
                yield {slice_field: record["account_id"]}

class Customers(CanopyStream):

    primary_key = "customer_id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "customers"
    
    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json["results"]
        #for record in response.json()["results"]:
        #    yield record

class Accounts(CanopyStream):

    primary_key = "account_id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "customers/accounts"
    
    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        for record in response.json()["results"]:
            yield record

class AccountRelatedStream(CanopyStream, ABC):    
    
    def stream_slices(
        self, sync_mode: SyncMode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        yield from self.read_slices_from_records(stream_class=Accounts, slice_field="account_id")

class LineItems(AccountRelatedStream):

    primary_key = "account_id"

    def path(self, stream_slice: Mapping[str, Any] = None, **kwargs) -> str:
        account_id = stream_slice["account_id"]
        return f"customers/{account_id}/line_items"

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        #return [response.json()]
        for record in response.json()["results"]:
            yield record


# Source
class SourceCanopy(AbstractSource):
   
    @staticmethod
    def _get_authenticator(config: dict):
        """
        Verifies that the information for setting the header has been set, and returns a class
        which overloads that standard authentication to include additional headers that are required by Webflow.
        """
        auth_token = config.get("auth_token", None)
        if not auth_token:
            raise Exception("Config validation error: 'auth_token' is a required property")

        auth = TokenAuthenticator(token=auth_token)
        return auth
    
    def check_connection(self, logger, config) -> Tuple[bool, any]:
        """
        See https://github.com/airbytehq/airbyte/blob/master/airbyte-integrations/connectors/source-stripe/source_stripe/source.py#L232
        for an example.

        :param config:  the user-input config object conforming to the connector's spec.yaml
        :param logger:  logger object
        :return Tuple[bool, any]: (True, None) if the input config can be used to connect to the API successfully, (False, error) otherwise.
        """
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
        """
        :param config: A Mapping of the user input configuration as defined in the connector spec.
        """
        args = {"authenticator": self._get_authenticator(config)}
        #auth = self._get_authenticator(config)
        return [
            Customers(**args),
            Accounts(**args),
            LineItems(**args)]