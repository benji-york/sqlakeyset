from __future__ import unicode_literals

from .columns import parse_clause, OC
from sqlalchemy import func
from functools import partial

from .results import Page, Paging, unserialize_bookmark

import sys


PER_PAGE_DEFAULT = 10

PY2 = sys.version_info[0] == 2

if not PY2:
    unicode = str


def where_condition_for_page(ordering_columns, place):
    row, place_row = paging_condition(ordering_columns, place)
    condition = func.row(*row) > func.row(*place_row)
    return condition


def orm_page_from_rows(
        rows,
        page_size,
        ocols,
        column_descriptions,
        backwards=False,
        current_marker=None):

    get_marker = partial(
        orm_placemarker_from_row,
        column_descriptions=column_descriptions)

    paging = Paging(rows, page_size, ocols, backwards, current_marker, get_marker)

    page = Page(paging.rows)
    page.paging = paging
    return page


def core_page_from_rows(
        rows,
        page_size,
        ocols,
        backwards=False,
        current_marker=None,
        keys=None):

    paging = Paging(rows, page_size, ocols, backwards, current_marker, core_placemarker_from_row)

    page = Page(paging.rows)
    page.paging = paging
    page._keys = keys
    return page


def orm_placemarker_from_row(row, ocols, column_descriptions):
    def value_from_thing(thing, desc, ocol):
        entity = desc['entity']
        expr = desc['expr']
        name = desc['name']

        if entity == expr:  # is a table
            if entity.__tablename__ == ocol.table_name:
                return getattr(thing, ocol.name)
            else:
                raise ValueError
        else:  # is an attribute
            if hasattr(expr, 'info'):
                mapper = expr.parent
                tname = mapper.local_table.description

                if ocol.table_name == tname and ocol.name == name:
                    return thing
                else:
                    raise ValueError
            else:
                if ocol.quoted_full_name == OC(expr).full_name:
                    return thing
                else:
                    raise ValueError

    def get_value(ocol):
        if len(column_descriptions) == 1:
            desc = column_descriptions[0]
            try:
                return value_from_thing(row, desc, ocol)
            except ValueError:
                pass
        else:
            for thing, desc in zip(row, column_descriptions):
                try:
                    return value_from_thing(thing, desc, ocol)
                except ValueError:
                    continue

        CANT_FIND = "can't find value for column {} in the results returned"
        raise ValueError(CANT_FIND.format(ocol.full_name))
    return tuple(get_value(x) for x in ocols)


def core_placemarker_from_row(row, ocols):
    def get_value(ocol):
        return row[ocol.name]
    return tuple(get_value(x) for x in ocols)


def orm_get_page(q, per_page, place, backwards):
    ob_clause = q.selectable._order_by_clause

    order_cols = parse_clause(ob_clause)

    if backwards:
        order_cols = [c.reversed for c in order_cols]

    clauses = [c.uo for c in order_cols]
    q = q.order_by(False).order_by(*clauses)

    if place:
        condition = where_condition_for_page(order_cols, place)
        q = q.filter(condition)

    q = q.limit(per_page + 1)

    rows = q.all()

    page = orm_page_from_rows(
        rows,
        per_page,
        order_cols,
        q.column_descriptions,
        backwards,
        current_marker=place)

    return page


def core_get_page(s, selectable, per_page, place, backwards):
    order_cols = parse_clause(selectable._order_by_clause)

    if backwards:
        order_cols = [c.reversed for c in order_cols]
    clauses = [x.uo for x in order_cols]

    selectable = selectable.order_by(None).order_by(*clauses)

    if place:
        where = where_condition_for_page(order_cols, place)
        selectable = selectable.where(where)

    selectable = selectable.limit(per_page + 1)

    selected = s.execute(selectable)
    rowkeys = selected.keys()
    rows = selected.fetchall()

    page = core_page_from_rows(
        rows,
        per_page,
        order_cols,
        backwards,
        current_marker=place,
        keys=rowkeys)

    return page


def paging_condition(ordering_columns, place):
    if len(ordering_columns) != len(place):
        raise ValueError('bad paging value')

    def swapped_if_descending(c, value):
        if not c.is_ascending:
            return value, c.uo.element
        else:
            return c.uo.element, value

    zipped = zip(ordering_columns, place)
    swapped = [swapped_if_descending(c, value) for c, value in zipped]
    row, place_row = zip(*swapped)
    return row, place_row


def process_args(after=False, before=False, page=False):
    if isinstance(page, unicode):
        page = unserialize_bookmark(page)

    if before is not False and after is not False:
        raise ValueError('after *OR* before')

    if (before is not False or after is not False) and page is not False:
        raise ValueError('specify either a page tuple, or before/after')

    if page:
        place, backwards = page
    elif after:
        place = after
        backwards = False
    elif before:
        place = before
        backwards = True
    else:
        backwards = False
        place = None

    return place, backwards


def select_page(
        s,
        selectable,
        per_page=PER_PAGE_DEFAULT,
        after=False,
        before=False,
        page=False):

    place, backwards = process_args(after, before, page)

    return core_get_page(
        s,
        selectable,
        per_page,
        place,
        backwards)


def get_page(
        q,
        per_page=PER_PAGE_DEFAULT,
        after=False,
        before=False,
        page=False):

    place, backwards = process_args(after, before, page)

    return orm_get_page(
        q,
        per_page,
        place,
        backwards)
