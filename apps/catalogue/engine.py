"""The labour-value engine (docs/04 section 6). Pure functions: no database, floats allowed here only (CLAUDE.md)."""

import warnings
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix, identity, lil_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import MatrixRankWarning, spsolve


@dataclass
class OfferData:
    id: int
    item_id: int
    q: float  # batch_size (products) or capacity (services)
    l: float  # hours per unit (declared or measured)  # noqa: E741
    d: float  # depreciation hours per unit (unicorn_owned tools)
    m: float  # euros per unit (buy_outside inputs + euro-bought tools)
    inputs: list[tuple[int, float, int | None]]  # (item_id, quantity_per_batch, preferred_supplier_offer_id)


@dataclass
class ValueResult:
    direct: float
    indirect: float
    total: float
    euro: float
    error: str | None = None


@dataclass
class SolveInfo:
    method: str  # "spsolve" or "jacobi"
    converged: bool


def build_matrix(offers, weights):
    """M[k, j] = how much of offer k's item one unit of offer j needs."""
    idx = {o.id: n for n, o in enumerate(offers)}
    size = len(offers)
    m = lil_matrix((size, size))
    for j, offer in enumerate(offers):
        for item_id, quantity, preferred in offer.inputs:
            per_unit = quantity / offer.q
            if preferred is not None:
                m[idx[preferred], j] += per_unit
                continue
            if item_id not in weights or not weights[item_id]:
                raise ValueError(f"No supplier weights for item {item_id}")
            for offer_id, share in weights[item_id].items():
                m[idx[offer_id], j] += per_unit * share
    return m.tocsr()


def _topological_order(m):
    """Offers in an order where every supplier comes before its users, or None when there is a cycle (Kahn)."""
    coo = m.tocoo()
    size = m.shape[0]
    indegree = np.zeros(size, dtype=int)
    for k, j in zip(coo.row, coo.col, strict=True):
        if k == j:
            return None
        indegree[j] += 1
    users = [[] for _ in range(size)]
    for k, j in zip(coo.row, coo.col, strict=True):
        users[k].append(j)
    ready = [i for i in range(size) if indegree[i] == 0]
    order = []
    while ready:
        k = ready.pop()
        order.append(k)
        for j in users[k]:
            indegree[j] -= 1
            if indegree[j] == 0:
                ready.append(j)
    return np.array(order) if len(order) == size else None


def _direct_solve(m, rhs_list):
    size = m.shape[0]
    order = _topological_order(m)
    if order is not None:
        # Without cycles the system is triangular once sorted: no fill-in, so this is fast for any size.
        m = m[order][:, order].tocsr()
        rhs_list = [rhs[order] for rhs in rhs_list]
        spec = "NATURAL"
    else:
        spec = "COLAMD"
    a = (identity(size, format="csc") - m).T.tocsc()
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("error", MatrixRankWarning)
        for rhs in rhs_list:
            x = np.asarray(spsolve(a, rhs, permc_spec=spec)).reshape(-1)
            if order is not None:
                back = np.empty_like(x)
                back[order] = x
                x = back
            out.append(x)
    return out


def _acceptable(x):
    return bool(np.all(np.isfinite(x)) and np.all(x >= -1e-12))


def _jacobi(m, rhs, rounds=1000, tol=1e-6):
    v = rhs.copy()
    mt = m.T.tocsr()
    for _ in range(rounds):
        new = rhs + mt @ v
        if not np.all(np.isfinite(new)):
            return new, False
        if np.max(np.abs(new - v)) < tol:
            return new, True
        v = new
    return v, False


def _loop_members(m):
    size = m.shape[0]
    count, labels = connected_components(m, directed=True, connection="strong")
    sizes = np.bincount(labels, minlength=count)
    in_cycle = sizes[labels] > 1
    diagonal = m.diagonal() != 0
    return np.where(in_cycle | diagonal)[0] if size else np.array([], dtype=int)


def _solve_matrix(m, l_plus_d, e_rhs):
    """Returns (v, e, SolveInfo) or raises ArithmeticError when there is a loop."""
    try:
        v, e = _direct_solve(m, [l_plus_d, e_rhs])
        if _acceptable(v) and _acceptable(e):
            return v, e, SolveInfo("spsolve", True)
    except (MatrixRankWarning, RuntimeError, ValueError):
        pass
    v, ok_v = _jacobi(m, l_plus_d)
    e, ok_e = _jacobi(m, e_rhs)
    if ok_v and ok_e and _acceptable(v) and _acceptable(e):
        return v, e, SolveInfo("jacobi", True)
    raise ArithmeticError("loop")


def solve(offers, weights, info=None) -> dict[int, ValueResult]:
    """weights[item_id][offer_id] = share of that offer in the item's supply (sums to 1 per item).

    Pass a dict as `info` to get {"method": ..., "converged": ...} back.
    """
    size = len(offers)
    if size == 0:
        return {}
    m = build_matrix(offers, weights)
    l = np.array([o.l for o in offers], dtype=float)  # noqa: E741
    ld = l + np.array([o.d for o in offers], dtype=float)
    eur = np.array([o.m for o in offers], dtype=float)
    bad = set()
    try:
        v, e, run = _solve_matrix(m, ld, eur)
    except ArithmeticError:
        bad = set(int(i) for i in _loop_members(m))
        keep = np.array([i for i in range(size) if i not in bad], dtype=int)
        v = np.zeros(size)
        e = np.zeros(size)
        run = SolveInfo("jacobi", False)
        if len(keep):
            sub = m[keep][:, keep]
            try:
                sv, se, run2 = _solve_matrix(sub, ld[keep], eur[keep])
                v[keep], e[keep] = sv, se
                run = SolveInfo(run2.method, False)
            except ArithmeticError:
                bad = set(range(size))
    if info is not None:
        info.update({"method": run.method, "converged": run.converged})
    results = {}
    for n, offer in enumerate(offers):
        if n in bad:
            results[offer.id] = ValueResult(l[n], 0.0, 0.0, 0.0, "loop")
        else:
            results[offer.id] = ValueResult(float(l[n]), float(v[n] - l[n]), float(v[n]), float(e[n]), None)
    return results


# Kept for readers who look for the matrix type named in the plan.
__all__ = ["OfferData", "ValueResult", "solve", "build_matrix", "csr_matrix"]
