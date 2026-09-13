# -*- coding: utf-8 -*-
"""T-116: 都道府県コード表。SPEC F-01 / D-06。

期待値の出所: JIS X 0401(都道府県コード)。01 北海道 〜 47 沖縄県。
OSM の area 指定は ISO 3166-2:JP(`JP-13` の形)で、数字部分は JIS X 0401 と同じ。
"""
import pytest

from etl.geo_features import PREF_CRS
from etl.prefectures import PREF_CODE_NAME, code_from_area


@pytest.mark.unit
def test_t116_table_has_47_codes_in_order():
    """T-116: 47 件・01〜47 の連番。"""
    assert list(PREF_CODE_NAME) == [f"{i:02d}" for i in range(1, 48)]


@pytest.mark.unit
@pytest.mark.parametrize(
    "code,name",
    [("01", "北海道"), ("13", "東京都"), ("19", "山梨県"), ("26", "京都府"),
     ("27", "大阪府"), ("47", "沖縄県")],
)
def test_t116b_known_anchors(code, name):
    """T-116: JIS X 0401 の既知の対応。"""
    assert PREF_CODE_NAME[code] == name


@pytest.mark.unit
def test_t116c_names_agree_with_the_crs_table():
    """T-116: 県名の集合が平面直角座標系の表と一致する。

    二つの表を別々に手で書いているので、片方だけ綴りが違うと
    その県だけ距離の計算が黙って落ちる。**表どうしを突き合わせる。**
    """
    assert set(PREF_CODE_NAME.values()) == set(PREF_CRS)


@pytest.mark.network
def test_t116e_names_match_osm_iso3166_2():
    """T-116 [network]: 県名を OSM の ISO3166-2 の name と突き合わせる。

    **番号で書いた表は、隣の番号も実在するので黙って動く**(HC-262)。この表は
    取得の経路そのもの(`JP-13` の問い合わせで返った神社を「東京都」と呼ぶ)なので、
    こちらの記憶ではなく**実際にその area が何と名乗っているか**に当てて確かめる。

    `-m network` を付けたときだけ走る(外部の可用性で CI を落とさないため)。
    """
    import httpx

    from etl.fetch_osm import ENDPOINT, USER_AGENT

    q = '[out:json][timeout:180];relation["ISO3166-2"~"^JP-"]["admin_level"="4"];out tags;'
    r = httpx.post(ENDPOINT, data={"data": q}, headers={"User-Agent": USER_AGENT}, timeout=240.0)
    r.raise_for_status()
    got = {}
    for el in r.json().get("elements", []):
        t = el.get("tags") or {}
        if t.get("ISO3166-2") and t.get("name"):
            got[t["ISO3166-2"]] = t["name"]

    # 対照が成り立つ前提 —— 47 件そろって初めて突き合わせになる
    assert len(got) >= 47, f"OSM から取れた都道府県が {len(got)} 件しかない: {sorted(got)[:5]}"

    mismatches = [
        (code, name, got.get(f"JP-{code}"))
        for code, name in PREF_CODE_NAME.items()
        if got.get(f"JP-{code}") != name
    ]
    assert mismatches == [], f"県コード表と OSM の名前が食い違う: {mismatches}"


@pytest.mark.unit
def test_t116d_code_from_area():
    """T-116: ISO 3166-2:JP の area から県コードを取る。当たらなければ例外。"""
    assert code_from_area("JP-13") == "13"
    assert code_from_area("JP-01") == "01"
    with pytest.raises(ValueError):
        code_from_area("JP")        # 全国ファイルには県が無い
    with pytest.raises(ValueError):
        code_from_area("JP-48")     # 存在しない県
    with pytest.raises(ValueError):
        code_from_area("US-CA")
