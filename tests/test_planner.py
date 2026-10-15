from transcript.converters.base import Converter, Edge
from transcript.planner import MAX_CATEGORY_CHANGES, plan

C = Converter()


def e(src, dst, cost=1.0, terminal=False, first_only=False):
    return Edge(src, dst, C, cost, terminal, first_only)


def test_direct_and_chained_routes():
    routes = plan("md", [e("md", "typ"), e("typ", "pdf"), e("pdf", "png", terminal=True)])
    assert routes["typ"].via == []
    assert routes["pdf"].via == ["typ"]
    assert routes["png"].via == ["typ", "pdf"]


def test_cheapest_route_wins():
    edges = [e("docx", "pdf", cost=1.0), e("docx", "odt", cost=0.5), e("odt", "pdf", cost=0.5)]
    assert plan("docx", edges)["pdf"].via == []  # fewer steps win thanks to the hop penalty
    edges = [e("docx", "pdf", cost=3.0), e("docx", "odt", cost=0.5), e("odt", "pdf", cost=0.5)]
    assert plan("docx", edges)["pdf"].via == ["odt"]


def test_terminal_edges_end_the_route():
    routes = plan("pdf", [e("pdf", "png", terminal=True), e("png", "jpg")])
    assert "png" in routes and "jpg" not in routes


def test_first_only_edges():
    edges = [e("gif", "mp4", first_only=True), e("png", "gif")]
    assert "mp4" in plan("gif", edges)
    assert "mp4" not in plan("png", edges)


def test_first_step_filter_only_applies_to_the_first_step():
    edges = [e("mp4", "mp3"), e("mp4", "mkv"), e("mkv", "mp3", cost=5)]
    routes = plan("mp4", edges, first_step_ok=lambda edge: edge.dst != "mp3")
    assert routes["mp3"].via == ["mkv"]


def test_category_changes_are_limited():
    # video -> text -> document -> image would be a picture of a transcript
    edges = [e("mp4", "txt"), e("txt", "pdf"), e("pdf", "png")]
    routes = plan("mp4", edges)
    assert MAX_CATEGORY_CHANGES == 2
    assert "pdf" in routes and "png" not in routes


def test_source_is_never_a_target():
    routes = plan("png", [e("png", "jpg"), e("jpg", "png")])
    assert set(routes) == {"jpg"}
