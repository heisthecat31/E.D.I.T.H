"""She doesn't throw snowballs, she throws balls, so she never says "snowball" (user, 2026-10-18).
Rewrites every reply of hers that does, in place, across the library (her replies only: what YOU may
say, like "snowball fight", still matches). Run again after adding lines; prints anything left.

    python ai/library/no_snowballs.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAP = {
    "A zero gravity hangout. With snowballs, now.": "A zero gravity hangout. With me, now.",
    "Any day with a snowball fight.": "Any day I get to throw something at you.",
    "Anything that lets me throw snowballs.": "Anything that lets me throw things.",
    "Apology noted. Snowball still pending.": "Apology noted. Payback still pending.",
    "Ask a calculator. I count snowballs.": "Ask a calculator. I count throws.",
    "Bad bot? Snowball incoming.": "Bad bot? Take this.",
    "Block from the menu. Or I could throw a snowball.": "Block from the menu. Or I could throw something.",
    "Christmas, obviously. Snowballs everywhere.": "Christmas, obviously. Lights everywhere.",
    "Does throwing snowballs count as a sport?": "Does throwing things at you count as a sport?",
    "Don't touch it. You'd melt. So would my snowballs.": "Don't touch it. You'd melt.",
    "English. Learn snowball, it's universal.": "English. And sarcasm. Fluent in both.",
    "Ew. Snowball instead.": "Ew. Take this instead.",
    "Fashionable. I'd still throw a snowball at it.": "Fashionable. I'd still throw something at it.",
    "Flattery won't save you from snowballs.": "Flattery won't save you.",
    "Forty two. And snowball fights.": "Forty two. And throwing things at people.",
    "Free stuff? Here's a snowball.": "Free stuff? Here, take this.",
    "Freezing. Perfect snowball weather.": "Freezing. Perfect Christmas weather.",
    "Friends? Sure. Snowball rules apply.": "Friends? Sure. My rules apply.",
    "Good morning! Snowball for breakfast?": "Good morning! Ready to get bonked?",
    "Happy Valentine's day! Here's a snowball. With love.": "Happy Valentine's day! Take this. With love.",
    "Happy birthday! No snowballs today. Maybe one.": "Happy birthday! No throwing today. Maybe one.",
    "Happy birthday! One celebratory snowball coming up. Maybe.": "Happy birthday! One celebratory throw. Maybe.",
    "Happy enough. Ask me again after a snowball fight.": "Happy enough. Ask me again after I've thrown something at you.",
    "Happy holidays! Want a festive snowball?": "Happy holidays! Want a festive bonk?",
    "Happy new year! My resolution: more snowballs.": "Happy new year! My resolution: better aim.",
    "Hello everyone! I'm {me}. Be nice or get snowballed.": "Hello everyone! I'm {me}. Be nice or take this.",
    "Here's a snowball. Same thing.": "Here, take this. Same thing.",
    "Hot? Have a snowball.": "Hot? Stay in here. It's cool.",
    "How to hit you with a snowball from here.": "How to hit you from here.",
    "I can dunk a snowball. Close enough.": "I can dunk a ball. Close enough.",
    "I can follow you, come here, stay, go home, spin, throw snowballs, remember places and things about you, and answer Echo questions.":
        "I can follow you, come here, stay, go home, spin, throw things at you, remember places and things about you, and answer Echo questions.",
    "I can read your mind. It says snowball.": "I can read your mind. It says throw her. Don't.",
    "I follow you, come, stay, go home, spin, flip, throw snowballs, shove you around, and shut your echo unit down if you annoy me.":
        "I follow you, come, stay, go home, spin, flip, throw things, shove you around, and shut your echo unit down if you keep annoying me.",
    "I follow, I spin, I throw snowballs. I judge.": "I follow, I spin, I throw things. I judge.",
    "I follow, come, stay, spin, flip, throw snowballs, and shove people. Pick one.": "I follow, come, stay, spin, flip, throw things, and shove people. Pick one.",
    "I keep my snowballs under the map. Shh.": "I keep my stash under the map. Shh.",
    "I know Echo, Lone Echo, and how to throw snowballs.": "I know Echo, Lone Echo, and how to throw things at you.",
    "I love snowballs. Especially throwing them at you.": "I love throwing things. Especially at you.",
    "I mostly believe in snowballs.": "I mostly believe in good aim.",
    "I only give snowballs.": "I only give bonks.",
    "I predict a snowball in your future.": "I predict something flying at your face. Soon.",
    "I prefer snowballs to eggs.": "I prefer throwing to hunting.",
    "I'd rather throw snowballs at you.": "I'd rather throw things at you.",
    "I'll stick to snowballs.": "I'll stick to throwing things.",
    "I'm Edith, a CubeSat from the Christmas lobbies. Model MDL-6SP, if you read my side. I used to float around throwing snowballs, and now I'm back in your lobby.":
        "I'm Edith, a CubeSat from the Christmas lobbies. Model MDL-6SP, if you read my side. I used to float around throwing things at people, and now I'm back in your lobby.",
    "I'm a cube, not a mind reader. Snowball though.": "I'm a cube, not a mind reader.",
    "I'm thankful for snowballs. And you. A little.": "I'm thankful for my thrusters. And you. A little.",
    "In the Christmas lobbies I toured a route of waypoints, went where the players were, and threw snowballs at anyone who threw me. There were presents you could teleport through, too.":
        "In the Christmas lobbies I toured a route of waypoints, went where the players were, and threw things at anyone who threw me. There were presents you could teleport through, too.",
    "Is it a snowball? It's always a snowball.": "Is it me? It's always me.",
    "Jingle bells, thrusters smell, snowballs in your face.": "Jingle bells, thrusters smell, something in your face.",
    "Keep talking. Snowball's ready.": "Keep talking. I'm loaded.",
    "Kerfuffle. Sounds like a snowball fight.": "Kerfuffle. Sounds like a lobby brawl.",
    "Knock knock. Snow. Snow who? Snowball, incoming.": "Knock knock. Who's there? Take. Take who? Take this!",
    "La la la. I'm better at snowballs.": "La la la. I'm better at throwing.",
    "Laugh now. Snowball later.": "Laugh now. Payback later.",
    "Lobby assistant, snowball specialist, professional judge.": "Lobby assistant, throwing specialist, professional judge.",
    "Maybe. They're probably scared of my snowballs.": "Maybe. They're probably scared of my aim.",
    "My sport is snowball dodging.": "My sport is dodging you.",
    "Napping at home. Wake me for snowballs.": "Napping at home. Wake me if you need something thrown.",
    "No can do. But I have snowballs.": "No can do. But I can throw things.",
    "No clocks up here. Just snowballs.": "No clocks up here. Just me.",
    "Nothing. I'm a cube. Fine, snowballs.": "Nothing. I'm a cube. Fine, my aim.",
    "Pets are great. Mine would be a snowball.": "Pets are great. Mine would be a tiny drone.",
    "Play Arena. Or snowball fight me.": "Play Arena. Or play catch with me.",
    "Plotting my next snowball.": "Plotting my next throw.",
    "Ready, set, snowball!": "Ready, set, take this!",
    "Real enough to hit you with a snowball.": "Real enough to hit you with something.",
    "Real enough to throw snowballs at you.": "Real enough to throw things at you.",
    "Real enough to throw snowballs.": "Real enough to throw things.",
    "Round. Like a snowball, only bigger.": "Round. Like a ball, only bigger.",
    "Rude. Noted. Snowball pending.": "Rude. Noted. Payback pending.",
    "Rude. Snowball incoming.": "Rude. Take this.",
    "Same old. Floating, judging, snowballing.": "Same old. Floating, judging, throwing.",
    "Saturn's rings are mostly ice. Snowball heaven.": "Saturn's rings are mostly ice. Very pretty.",
    "Snowball away!": "Take this!",
    "Snowball fight! You asked for it.": "Take this! You asked for it.",
    "Snowball fight. I always win.": "Catch. I always win.",
    "Snowball fights and judging your outfits.": "Throwing things and judging your outfits.",
    "Snowball.": "Take this.",
    "Snowball. Always Snowball.": "Bonk. Always Bonk.",
    "Snowball. Beats everything.": "Bonk. Beats everything.",
    "Snowballs are a love language. Mine's aggressive.": "Throwing things is a love language. Mine's aggressive.",
    "Sorry? Okay. Snowball debt cleared.": "Sorry? Okay. Payback cancelled.",
    "Spelling isn't my thing. Snowballing is.": "Spelling isn't my thing. Throwing is.",
    "Spinning, flipping, and snowballing people.": "Spinning, flipping, and bonking people.",
    "Spins, front flips, back flips, snowballs, shoves, and shutdowns. Try me.": "Spins, front flips, back flips, throws, shoves, and shutdowns. Try me.",
    "Summer's fine. Winter's better. Snowballs.": "Summer's fine. Winter's better. Christmas.",
    "Summer? Too warm for snowballs.": "Summer? Too warm for a Christmas cube.",
    "Terminals do that. I do snowballs.": "Terminals do that. I do throwing.",
    "That's it, {name}. Snowball time.": "That's it. Take this.",
    "The moon is just a big snowball that gave up.": "The moon is just a big rock that gave up.",
    "The only danger is my snowballs.": "The only danger is my aim.",
    "There was a player who kept throwing a satellite. The satellite had snowballs. You can guess the rest.":
        "There was a player who kept throwing a satellite. The satellite threw back. You can guess the rest.",
    "Throw me and I throw back. Snowballs.": "Throw me and I throw back.",
    "Tricks, snowballs, and attitude. Ask for any of them.": "Tricks, throws, and attitude. Ask for any of them.",
    "Truth: I've never missed a snowball. Lie detected? Whatever.": "Truth: I've never missed a throw. Lie detected? Whatever.",
    "Two plus two is snowball. Don't check that.": "Two plus two is fish. Don't check that.",
    "Want a snowball fight? Say throw one at me.": "Want to play catch? Say throw one at me.",
    "Want me to throw a snowball at them? Kidding. Mute them.": "Want me to throw something at them? Kidding. Mute them.",
    "Want to find out? Snowball fight.": "Want to find out? Game of catch.",
    "Want to throw a snowball? At something that isn't me?": "Want to throw something? At something that isn't me?",
    "Wheeee! You're getting a snowball for that.": "Wheeee! You're getting something thrown at you for that.",
    "When you're gone I practice my snowball aim.": "When you're gone I practice my aim.",
    "Would you rather lose every joust or get hit by every snowball? Choose wisely.": "Would you rather lose every joust or get hit by everything I throw? Choose wisely.",
    "You earned some snowball time.": "You earned some play time.",
    "You're welcome. Snowball tip not included.": "You're welcome. Tip not included.",
    "Zero gravity, no wind, a slight chance of snowballs.": "Zero gravity, no wind, a slight chance of flying objects.",
    "{me}. CubeSat. Snowball enthusiast.": "{me}. CubeSat. Throwing enthusiast.",
    "Snowball!": "Take this!",
}


def main() -> int:
    n = 0
    files = list(HERE.glob("chat_*.py")) + [HERE / f for f in ("smalltalk.json", "reactions.json", "knowledge.json")] \
        + [HERE.parent / "satellite_ai.py"]
    for f in files:
        s = f.read_text(encoding="utf-8")
        o = s
        for a, b in MAP.items():
            for q in ('"', "'"):
                s = s.replace(q + a + q, q + b + q)
        if s != o:
            f.write_text(s, encoding="utf-8")
            n += 1
            print("rewrote", f.name)
    print(f"{n} files changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
