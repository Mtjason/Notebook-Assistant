from pathlib import PurePosixPath as P

from notebook_assistant.domain.links import (
    Resolver,
    find_links,
    md_target_for,
    render_link,
    rewrite_links,
    wiki_target_for,
)


def test_wikilink_forms() -> None:
    text = "[[A]] ![[img.png]] [[B#Head|alias]] [[C#^blk]] [[#Local]] [[dir/D]]"
    links = find_links(text)
    assert [(lk.target, lk.subpath, lk.alias, lk.embed) for lk in links] == [
        ("A", "", None, False),
        ("img.png", "", None, True),
        ("B", "#Head", "alias", False),
        ("C", "#^blk", None, False),
        ("", "#Local", None, False),
        ("dir/D", "", None, False),
    ]


def test_markdown_links() -> None:
    text = '[x](a%20b.md) ![i](<pics/c d.png>) [w](https://example.com) [t](n.md "T")'
    links = find_links(text)
    assert [(lk.target, lk.encoded, lk.angle, lk.embed) for lk in links] == [
        ("a b.md", True, False, False),
        ("pics/c d.png", False, True, True),
        ("n.md", False, False, False),
    ]


def test_code_is_ignored() -> None:
    text = "```\n[[no]]\n```\n`[[no]]` [[yes]]\n~~~md\n[[no]]\n~~~\n"
    assert [lk.target for lk in find_links(text)] == ["yes"]


def test_table_escaped_pipe_round_trips() -> None:
    link = find_links("| [[x/y\\|Y]] |")[0]
    assert (link.target, link.alias, link.table_escape) == ("x/y", "Y", True)
    assert render_link(link, "z") == "[[z\\|Y]]"


def test_resolution_follows_obsidian() -> None:
    files = [
        P("60-Knowledge/Software/Python os.execv.md"),
        P("A/note.md"),
        P("B/note.md"),
        P("Attachments/img.png"),
        P("A/sub/deep.md"),
    ]
    r = Resolver(files)
    src_a = P("A/other.md")

    def res(text: str, source: P = src_a) -> P | None:
        return r.resolve(find_links(text)[0], source)

    assert res("[[Python os.execv]]") == files[0]  # dotted title is still a note
    assert res("[[python OS.execv]]") == files[0]  # case-insensitive
    assert res("[[note]]") == P("A/note.md")  # same folder wins
    assert res("[[note]]", P("C/x.md")) == P("A/note.md")  # then shortest/alphabetical
    assert res("[[B/note]]") == P("B/note.md")
    assert res("[[sub/deep]]") == P("A/sub/deep.md")  # path suffix
    assert res("![[img.png]]") == files[3]
    assert res("[i](../Attachments/img.png)") == files[3]  # relative
    assert res("[i](Attachments/img.png)") == files[3]  # from the root
    assert res("[[missing]]") is None
    assert res("[[#Local]]") == src_a


def test_rewrite_keeps_everything_else() -> None:
    text = "a [[Old|x]] b [[Old#H]] c [[Keep]]"
    out = rewrite_links(text, lambda lk: render_link(lk, "New") if lk.target == "Old" else None)
    assert out == "a [[New|x]] b [[New#H]] c [[Keep]]"


def test_target_styles() -> None:
    bare = find_links("[[Old]]")[0]
    pathy = find_links("[[dir/Old]]")[0]
    new = P("X/New name.md")
    assert wiki_target_for(new, bare, bare_name_is_unique=True) == "New name"
    assert wiki_target_for(new, bare, bare_name_is_unique=False) == "X/New name"
    assert wiki_target_for(new, pathy, bare_name_is_unique=True) == "X/New name"
    assert wiki_target_for(P("Attachments/n.png"), bare, bare_name_is_unique=True) == "n.png"

    md = find_links("[d](../A/Old%20one.md)")[0]
    out = md_target_for(P("B/New one.md"), md, P("C/src.md"), was_relative=True)
    assert out == "../B/New%20one.md"
    md_abs = find_links("[d](A/Old)")[0]
    assert md_target_for(P("B/New.md"), md_abs, P("C/s.md"), was_relative=False) == "B/New"
    paren = find_links("[d](Old.md)")[0]
    out = md_target_for(P("A (v2).md"), paren, P("s.md"), was_relative=False)
    assert out == "A%20%28v2%29.md"
