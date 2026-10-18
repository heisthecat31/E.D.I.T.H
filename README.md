# E.D.I.T.H

**E**ven **D**ead **I**'m **T**he **H**ero: a joke from *Spider-Man: Far From Home*.

The Christmas CubeSat brought back into Echo VR's live lobby as **E.D.I.T.H**, "the new AI for the
Echo Construct": she flies, follows, tumbles, stares, throws balls at people who throw her, shoves and
shuts down bullies, changes face with her mood, and talks (her brain runs on SparkAPI; see `docs/`).
One Edith per match: players with the mod share her through the relay (`docs/networkplan.md`).

| Happy | Surprised | Angry |
|:---:|:---:|:---:|
| <img src="docs/images/edith_happy.webp" width="260" alt="E.D.I.T.H smiling, her thruster jets out"> | <img src="docs/images/edith_surprised.webp" width="260" alt="E.D.I.T.H surprised, grabbed by a player"> | <img src="docs/images/edith_angry.webp" width="260" alt="E.D.I.T.H angry"> |

## What she can do

- **Fly on her own.** She hovers by her home spot, follows people around, and fires her thruster jets
  as she moves. Grab her, throw her, or knock her with your head and she tumbles, then turns round and
  stares at whoever did it.
- **Talk.** Say her name first: *"Edith, ..."*. She answers small talk, questions about Echo VR and Lone
  Echo, and a lot of nonsense, in her own voice. If she doesn't know something yet, she says so.
- **Take orders.** *Follow me*, *come here*, *stay*, *go home*, *spin*, *front flip* / *back flip*,
  *keep spinning*, *stop*, *push me*, *throw one at me*.
- **Remember places.** *"Remember this spot as the court"*, then later *"go to the court"*.
- **Learn.** *"When someone says X, say Y"* teaches her a new answer, and she remembers what you tell her
  about yourself (likes, dislikes, favourites).
- **Know who's who.** Everyone with the mod shares one Edith. She knows who is talking to her and who
  did what to her, and keeps track of each person separately. She never says anyone's name.
- **Show how she feels.** Her face changes with her mood: happy, surprised, angry, dizzy, hurt, annoyed.
- **Respect mute.** While you're muted in game she ignores what you say.

## How to treat her

Be nice. She keeps a score for every player:

- Kind words (*"thanks Edith"*, *"you're the best"*) give you a **nice** point.
- Mean words, and grabbing, throwing, headbutting or hitting her, give you a **mean** point. If you're
  already on her good side, a grab is fine: she likes being held by a friend.
- Mean points fade over time (one every 90 seconds). Nice points stay, unless you do three mean things
  in a row: that wipes them all.
- Your score is nice points minus mean points. Bumping into a wall by herself doesn't count against
  anyone.

## What happens if you treat her badly

It escalates, and it's aimed at you, not at whoever is standing nearest:

| What you did | What she does |
|---|---|
| Threw her, or headbutted her | Stares you down, then throws a ball at you |
| Three mean things in a row | Wipes your nice points and throws a ball at you |
| Two more mean things while your score is below 0 | Shoves you across the room |
| Score of -5 or worse | Shuts your Echo unit down: you respawn |
| Score below 0 and you give an order | She refuses the first time; ask again (or say *please*) and she does it, grumbling |
| Score of -5 or worse with someone nicer around | Ignores you completely |
| Someone nicer gave her an order in the last minute | Busy with them: yours waits |

She always obeys **stop**. Asking her to shut you down doesn't work: you get a shove instead. To get back
on her good side, say sorry (it takes a mean point off), be kind to her, and leave her alone for a bit
while your mean points fade.

## Layout

| Path | What |
|---|---|
| `plugin/` | `EDITH.dll`: her behaviour (`satellite.cpp`), the relay client (`edith_net.cpp`), her lobby data from `.edith` packages (`edith_pack.cpp`) |
| `ai/` | her ears and voice (`edith_ears.py`, the companion that talks to her brain), the old local companion, her library, voice rendering |
| `tools/` | level build (`build_satellite.py`), her `.edith` package (`make_edith_pack.py`), faces, textures (`retexture.py`), voice pack, release (`make_release.py`) |
| `release/` | `install.bat`, `uninstall.bat`, the player README; `E.D.I.T.H-<version>.zip` is built here |
| `docs/` | plans: networking, her brain, the original satellite rules |
| `agent.md` | the working notes: every finding, address and decision, by session |

## Build

```bat
build_satellite_plugin.bat
python tools\build_satellite.py --name mpl_lobby_b2 --her-model --with-port --port-faces --at 0 2.3 0
python tools\make_edith_pack.py
python tools\make_release.py
```

`out/` (build output) and the release zip are not in git.
