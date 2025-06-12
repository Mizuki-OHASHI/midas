import io
import os
import zipfile
from typing import Dict

import pandas as pd
import requests
import streamlit as st

API_KEY = st.secrets["EDINET"]["API_KEY"]


def load_doc_list(year: int, month: int) -> pd.DataFrame:
    filepath = os.path.join("cache", f"documents_list_{year:04d}-{month:02d}.csv")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Document list for {year:04d}-{month:02d} not found.")
    df = pd.read_csv(filepath, index_col=0)
    df.dropna(subset=["docID", "filerName", "JCN"], inplace=True)
    df["JCN"] = df["JCN"].astype(int).astype(str)  # 法人番号を文字列に変換
    return df


def get_document(docID: str, api_key: str = API_KEY) -> Dict[str, pd.DataFrame]:
    url = f"https://disclosure.edinet-fsa.go.jp/api/v2/documents/{docID}?type=5&Subscription-Key={api_key}"
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(
            f"Error fetching document: {response.status_code} - {response.text}"
        )

    # zipデータが送られてくるので解凍して中のファイル名を取得する
    zip_bytes = io.BytesIO(response.content)
    df_dict: Dict[str, pd.DataFrame] = {}
    with zipfile.ZipFile(zip_bytes) as zf:
        file_names = zf.namelist()
        # csv ファイルなら df_dict に追加
        for name in file_names:
            if name.lower().endswith(".csv"):
                with zf.open(name) as f:
                    raw = f.read()
                    df_dict[name] = pd.read_csv(
                        io.BytesIO(raw), encoding="utf-16", sep="\t"
                    )

    return df_dict


def get_documents_by_corp_num(
    corp_num: str, documents_list: pd.DataFrame
) -> Dict[str, Dict[str, pd.DataFrame]]:
    if corp_num not in documents_list["JCN"].values:
        raise ValueError(f"法人番号 {corp_num} は文書リストに存在しません。")

    docs: Dict[str, Dict[str, pd.DataFrame]] = {}
    corp_record = documents_list[documents_list["JCN"] == corp_num]
    for _, row in corp_record.iterrows():
        csv_flag = row["csvFlag"]
        if csv_flag != 1:
            continue
        doc_id = row["docID"]
        docs[doc_id] = get_document(doc_id)
    return docs


def load_corp_list() -> pd.DataFrame:
    filepath = os.path.join("cache", "basic_info.csv")
    if not os.path.exists(filepath):
        raise FileNotFoundError("Corp list not found.")
    # ＥＤＩＮＥＴコード,提出者種別,上場区分,連結の有無,資本金,決算日,提出者名,提出者名（英字）,提出者名（ヨミ）,所在地,提出者業種,証券コード,提出者法人番号
    df = pd.read_csv(filepath, index_col=0, skiprows=1)
    df.dropna(subset=["提出者法人番号", "提出者名"], inplace=True)
    df["提出者法人番号"] = (
        df["提出者法人番号"].astype(int).astype(str)
    )  # 法人番号を文字列に変換
    return df


def main():
    year = 2024
    month = 11
    doc_list = load_doc_list(year, month)
    jcn_to_name_doc = {
        jcn: name for jcn, name in zip(doc_list["JCN"], doc_list["filerName"])
    }
    corp_list = load_corp_list()
    jcn_to_name = {
        jcn: name
        for jcn, name in zip(corp_list["提出者法人番号"], corp_list["提出者名"])
    }

    st.set_page_config(
        page_title="Malert Financials",
        page_icon=":money_with_wings:",
        layout="wide",
    )
    st.title("Malert Financials")

    corp_number = st.selectbox(
        "法人番号を選択してください",
        options=list(jcn_to_name.keys()),
        format_func=lambda x: "{corp_num} {corp_name}".format(
            corp_num=x,
            corp_name=jcn_to_name.get(x, "不明"),
        ),
        index=None,
    )

    if corp_number is None:
        st.warning("法人番号を選択してください。")
        return

    st.header("基本情報")

    is_listed = False
    corp_info = corp_list[corp_list["提出者法人番号"] == corp_number]
    if corp_info.empty:
        st.error("選択された法人番号の基本情報が見つかりません。")
    else:
        data = corp_info.to_dict(orient="records")[0]
        is_listed = data["上場区分"] == "上場"
        if is_listed:
            st.success("上場企業")
        else:
            st.warning("非上場企業")
        st.write(data)

    st.header("財務情報")
    if corp_number not in jcn_to_name_doc:
        st.error("選択された法人番号の財務情報が見つかりません。")
        st.info(
            "EDINET API では「日付→文書一覧」しか用意されていないため、今は 2024年11月に提出されたもののみを検索対象としています。"
        )
        return
    if st.button("法人の財務情報を取得"):
        try:
            documents = get_documents_by_corp_num(corp_number, doc_list)
            for doc_id, df_dict in documents.items():
                st.subheader(f"Document ID: {doc_id}")
                for file_name, df in df_dict.items():
                    st.write(f"File: {file_name}")
                    st.dataframe(df)
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")


if __name__ == "__main__":
    main()
