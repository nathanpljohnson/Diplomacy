"""Deterministic simulations for the shared-power order selector."""
import random

from diplomacy import Game
import pytest

import drunk_power
from drunk_power import automatic_orders, choose_orders


def test_random_builds_use_distinct_centers_and_russian_coasts():
    game = Game()
    game.clear_units("RUSSIA")
    game.set_units("RUSSIA", ["A MOS", "A WAR"])
    game.set_centers("RUSSIA", ["MOS", "WAR", "STP", "SEV"])
    game.set_current_phase("W1901A")

    for seed in range(30):
        orders = automatic_orders(game, "RUSSIA", random.Random(seed))
        assert len(orders) == 2
        assert all(order.endswith(" B") for order in orders)
        assert len({order.split()[1][:3] for order in orders}) == 2
        assert {order.split()[1][:3] for order in orders} <= {"MOS", "WAR", "STP", "SEV"}
        for order in orders:
            if order.split()[1][:3] == "STP":
                assert order in {"A STP B", "F STP/NC B", "F STP/SC B"}


def test_forced_removals_are_all_disbands():
    game = Game()
    game.clear_units("GERMANY")
    game.clear_centers("GERMANY")
    game.set_units("GERMANY", ["A BER", "A MUN", "F KIE"])
    game.set_centers("GERMANY", ["BER", "MUN"])
    game.set_current_phase("W1901A")

    for seed in range(20):
        orders = automatic_orders(game, "GERMANY", random.Random(seed))
        assert len(orders) == 1
        assert orders[0].endswith(" D")
        assert " ".join(orders[0].split()[:2]) in {"A BER", "A MUN", "F KIE"}


class RetreatGame:
    phase_type = "R"

    def __init__(self, retreats, legal):
        self.retreats = retreats
        self.legal = legal

    def get_all_possible_orders(self):
        return {"XXX": self.legal}

    def get_orderable_locations(self):
        return {"ITALY": ["XXX"]}

    def get_state(self):
        return {"retreats": {"ITALY": self.retreats}}


def test_retreat_matching_finds_maximum_assignment_across_seeds():
    # A can use X or Y; B can only use X. Greedy A->X would strand B.
    game = RetreatGame(
        ["A AAA", "A BBB"],
        ["A AAA R XXX", "A AAA R YYY", "A BBB R XXX"],
    )
    for seed in range(30):
        orders = automatic_orders(game, "ITALY", random.Random(seed))
        retreats = [order for order in orders if " R " in order]
        assert len(retreats) == 2
        assert {order.split()[-1] for order in retreats} == {"XXX", "YYY"}


def test_impossible_retreats_disband_only_unmatched_units():
    game = RetreatGame(
        ["A AAA", "A BBB", "A CCC"],
        ["A AAA R XXX", "A BBB R XXX"],
    )
    for seed in range(20):
        orders = automatic_orders(game, "ITALY", random.Random(seed))
        assert len(orders) == 3
        retreats = [order for order in orders if " R " in order]
        disbands = [order for order in orders if order.endswith(" D")]
        assert len(retreats) == 1
        assert len(disbands) == 2
        assert len({order.split()[-1] for order in retreats}) == 1


def _maximum_matching_size(graph, unit_index=0, used=frozenset()):
    if unit_index == len(graph):
        return 0
    best = _maximum_matching_size(graph, unit_index + 1, used)
    for destination in graph[unit_index]:
        if destination not in used:
            best = max(
                best,
                1 + _maximum_matching_size(graph, unit_index + 1, used | {destination}),
            )
    return best


def test_all_three_by_three_retreat_graphs_match_brute_force_maximum():
    units = ["A AAA", "A BBB", "A CCC"]
    destinations = ["XXX", "YYY", "ZZZ"]
    for mask in range(1 << (len(units) * len(destinations))):
        graph = [
            [destinations[j] for j in range(len(destinations))
             if mask & (1 << (i * len(destinations) + j))]
            for i in range(len(units))
        ]
        legal = [f"{unit} R {dest}" for unit, options in zip(units, graph) for dest in options]
        game = RetreatGame(units, legal)
        expected = _maximum_matching_size(graph)
        for seed in (11, 29):
            orders = automatic_orders(game, "ITALY", random.Random(seed))
            retreats = [order for order in orders if " R " in order]
            chosen_destinations = [order.split()[-1] for order in retreats]
            assert len(chosen_destinations) == len(set(chosen_destinations))
            assert len(retreats) == expected


def test_whole_sheet_selection_requires_seat_and_ready_nonempty_sheet(monkeypatch):
    doc = {
        "drunk_power": "TURKEY",
        "seats": {
            "FRANCE": {"id": "one", "name": "One"},
            "GERMANY": {"id": "two", "name": "Two"},
            "ITALY": {"id": "three", "name": "Three"},
            "RUSSIA": {"id": "four", "name": "Four"},
        },
        "drunk_submissions": {
            "one": {"orders": ["A PAR - BUR"], "ready": False},
            "two": {"orders": [], "ready": True},
            "three": {"orders": ["A ROM H"], "ready": True},
            "four": {"orders": ["A MOS H"], "ready": True},
            # A proposal without a matching seat cannot enter the draw.
            "orphan": {"orders": ["A PAR H"], "ready": True},
        },
    }
    seen = []

    def choose(candidates):
        seen.extend(candidates)
        return candidates[0]

    monkeypatch.setattr(drunk_power.RNG, "choice", choose)
    selected = choose_orders(doc, type("Movement", (), {"phase_type": "M"})())

    assert [(player["power"], sheet["orders"]) for player, sheet in seen] == [
        ("ITALY", ["A ROM H"]),
        ("RUSSIA", ["A MOS H"]),
    ]
    assert selected == {
        "power": "TURKEY",
        "mode": "player",
        "player_number": 3,
        "player_name": "Three",
        "player_power": "ITALY",
        "orders": ["A ROM H"],
    }


def test_eliminated_but_seated_player_remains_eligible(monkeypatch):
    # choose_orders selects among seats and submissions; it does not filter by
    # whether the seated power currently has units on the board.
    doc = {
        "drunk_power": "TURKEY",
        "seats": {"RUSSIA": {"id": "four", "name": "Four"}},
        "drunk_submissions": {"four": {"orders": ["A MOS H"], "ready": True}},
    }
    monkeypatch.setattr(drunk_power.RNG, "choice", lambda candidates: candidates[0])
    assert choose_orders(doc, type("Movement", (), {"phase_type": "M"})()) == {
        "power": "TURKEY",
        "mode": "player",
        "player_number": 1,
        "player_name": "Four",
        "player_power": "RUSSIA",
        "orders": ["A MOS H"],
    }


def test_no_eligible_sheets_returns_no_proposal(monkeypatch):
    doc = {
        "drunk_power": "TURKEY",
        "seats": {"FRANCE": {"id": "one", "name": "One"}},
        "drunk_submissions": {"one": {"orders": ["A PAR H"], "ready": False}},
    }
    monkeypatch.setattr(drunk_power.RNG, "choice", lambda _: pytest.fail("no choice expected"))
    assert choose_orders(doc, type("Movement", (), {"phase_type": "M"})()) == {
        "power": "TURKEY", "mode": "no_proposal", "orders": []
    }
