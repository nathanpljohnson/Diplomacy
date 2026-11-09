"""House-rule order selection for a shared, unclaimed drunk power."""
import secrets

RNG = secrets.SystemRandom()


def players(doc):
    # Stable seat order, independent of joining order; one ticket per person.
    seen = set()
    result = []
    for power in sorted(doc['seats']):
        seat = doc['seats'][power]
        if seat['id'] not in seen:
            seen.add(seat['id'])
            result.append(dict(number=len(result)+1, power=power, **seat))
    return result


def automatic_orders(game, power, rng=RNG):
    possible = game.get_all_possible_orders()
    legal = sorted({o for loc in game.get_orderable_locations()[power] for o in possible.get(loc, [])})
    if game.phase_type == 'A':
        count = game.get_state()['builds'][power]['count']
        if count < 0:
            return rng.sample([o for o in legal if o.endswith(' D')], -count)
        centers = {}
        for order in legal:
            if order.endswith(' B'):
                centers.setdefault(order.split()[1][:3], []).append(order)
        selected = rng.sample(list(centers), min(count, len(centers)))
        return [rng.choice(centers[center]) for center in selected]
    if game.phase_type == 'R':
        # Random maximum matching avoids disbanding two friendly units that
        # can retreat to different destinations. Enemy collisions adjudicate normally.
        units = list(game.get_state()['retreats'][power])
        rng.shuffle(units)
        choices = {u:[o for o in legal if o.startswith(u+' R ')] for u in units}
        for options in choices.values():
            rng.shuffle(options)
        destinations = {}
        def place(unit, visited):
            for order in choices[unit]:
                dest = order.split()[-1][:3]
                if dest in visited:
                    continue
                visited.add(dest)
                if dest not in destinations or place(destinations[dest][0], visited):
                    destinations[dest] = (unit, order)
                    return True
            return False
        for unit in units:
            place(unit, set())
        assigned = {unit:order for unit,order in destinations.values()}
        return [assigned.get(unit, unit+' D') for unit in units]
    return []


def choose_orders(doc, game):
    power = doc.get('drunk_power')
    if not power:
        return None
    if game.phase_type != 'M':
        return dict(power=power, mode='automatic', orders=automatic_orders(game,power))
    eligible = [(p,doc.get('drunk_submissions',{}).get(p['id'],{})) for p in players(doc)]
    eligible = [(p,s) for p,s in eligible if s.get('orders') and s.get('ready')]
    if not eligible:
        return dict(power=power, mode='no_proposal', orders=[])
    # Uniform selection among submitted sheets is equivalent to rerolling
    # the player die until a submitted sheet is found, without an endless loop.
    player, sheet = RNG.choice(eligible)
    return dict(power=power, mode='player', player_number=player['number'], player_name=player['name'], player_power=player['power'], orders=sheet['orders'])
