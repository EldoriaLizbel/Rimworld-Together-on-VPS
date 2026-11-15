const fieldHelp = {
  Name: ["Name shown to players in the server list."],
  Description: ["Short description shown alongside the server name."],
  MaxPlayers: ["Maximum simultaneous connections.", "players"],
  DiscordURL: ["Optional link to your Discord community."],
  SteamWorkshopURL: ["Optional link to the server's Workshop collection."],
  Verbosity: ["Higher levels include more detail in the game server console."],
  DisplayChatInConsole: ["Include player chat in the Docker output and server log."],
  UseUPnP: ["Ask a compatible router to forward the game port automatically."],
  EnableServerBrowser: ["Publish the server in the public RimWorld Together browser."],
  EnableServerTelemetry: ["Allow the game server to send upstream telemetry."],
  EnableMoTD: ["Send a welcome message when a player connects."],
  MessageOfTheDay: ["Text shown in the player's chat after connecting."],
  LoginNotifications: ["Announce successful logins in chat."],
  DisconnectNotifications: ["Announce player departures in chat."],
  AutomaticBackups: ["Run full server backups on a schedule."],
  IntervalHours: ["Time between scheduled full backups.", "hours"],
  AutomaticDeletion: ["Remove the oldest server archive when a new backup exceeds the retention count."],
  Amount: ["Number of full server archives to retain.", "backups"],
  Cooldown: ["Minimum wait for standard players before repeating this action. 1,000 ms = 1 second.", "ms"],
  MinimumPrice: ["Floor for the marketplace purchase price.", "Silver"],
  PriceMultiplier: ["Adjusts what buyers pay and sellers receive. A rate of 0.20 adds a 20% markup when the base price reaches the price floor.", "rate"],
  MaxEntriesPerPlayer: ["Maximum active marketplace listings per player.", "listings"],
  TimeInterval: ["Real-time interval between site reward checks. 60,000 ms = 1 minute.", "ms"],
  BuildingCost: ["Amount paid from a caravan's inventory to build one site.", "Silver"],
  RewardsCount: ["Amount awarded per eligible staffed site at each reward delivery.", "Silver"],
  IsDifficultyEnforced: ["Apply these difficulty settings to players' games. Leave off to let each player choose."],
  AllowBigThreats: ["Allow major threats such as raids and other dangerous incidents."],
  AllowViolentQuests: ["Allow quests that can involve combat."],
  AllowIntroThreats: ["Allow introductory threats early in a colony's progress."],
  PredatorsHuntHumanlikes: ["Allow predators to hunt humanlike pawns."],
  AllowExtremeWeatherIncidents: ["Allow extreme weather events."],
  PeacefulTemples: ["Use peaceful ancient complexes where the game's difficulty rules apply."],
  AllowCaveHives: ["Allow insect hives to spawn in caves."],
  UnwaveringPrisoners: ["Allow prisoners with unwavering loyalty."],
  AllowTraps: ["Allow construction of traps."],
  AllowTurrets: ["Allow construction of turrets."],
  AllowMortars: ["Allow construction of mortars."],
  ClassicMortars: ["Use RimWorld's classic mortar rules."],
  FixedWealthMode: ["Scale threats by time instead of relying on colony wealth."],
  NoBabiesOrChildren: ["Disable babies and children where the relevant expansion rules apply."],
  BabiesAreHealthy: ["Use the healthy-baby rule when births occur."],
  ChildRaidersAllowed: ["Allow children to appear among raiders."],
  ThreatScale: ["Scale the strength of threats. 1 is the base value.", "×"],
  CropYieldFactor: ["Multiply the amount harvested from crops.", "×"],
  MineYieldFactor: ["Multiply the amount recovered from mining.", "×"],
  ButcherYieldFactor: ["Multiply the amount recovered from butchering.", "×"],
  ResearchSpeedFactor: ["Multiply the speed of research.", "×"],
  QuestRewardValueFactor: ["Multiply the value of quest rewards.", "×"],
  RaidLootPointsFactor: ["Multiply the points available for loot carried by raiders.", "×"],
  MaintenanceCostFactor: ["Multiply maintenance costs used by game mechanics.", "×"],
  EnemyDeathOnDownedChanceFactor: ["Scale the chance that an enemy dies immediately when downed.", "×"],
  FoodPoisonChanceFactor: ["Scale the chance of food poisoning.", "×"],
  ManhunterChanceOnDamageFactor: ["Scale the chance an animal goes manhunter when injured.", "×"],
  PlayerPawnInfectionChanceFactor: ["Scale the chance wounds on player pawns become infected.", "×"],
  DiseaseIntervalFactor: ["Multiply the interval between disease incidents.", "×"],
  EnemyReproductionRateFactor: ["Multiply enemy reproduction rates where applicable.", "×"],
  DeepDrillInfestationChanceFactor: ["Scale the chance deep drilling triggers an infestation.", "×"],
  FriendlyFireChanceFactor: ["Scale the chance of hitting an ally when firing.", "×"],
  AdaptationEffectFactor: ["Scale the impact of storyteller adaptation on threats.", "×"],
  AdaptationGrowthRateFactorOverZero: ["Scale how fast positive storyteller adaptation grows.", "×"],
  LowPopConversionBoost: ["Scale the ideology conversion boost at low colony population.", "×"],
  ChildAgingRate: ["Multiply the rate at which children age.", "×"],
  AdultAgingRate: ["Multiply the rate at which adults age.", "×"],
  WastepackInfestationChanceFactor: ["Scale the chance wastepacks trigger an infestation.", "×"],
  NomadicMineableResourcesFactor: ["Scale mineable resources for nomadic gameplay.", "×"],
  ScariaRotChance: ["Chance a scaria-infected animal's corpse rots. 0.60 means 60%.", "0–1"],
  AllowInstantKillChance: ["Chance RimWorld permits an otherwise lethal instant kill. 1 means 100%.", "0–1"],
  TradePriceFactorLoss: ["Fraction applied to RimWorld trade prices. 0 leaves the base prices in place.", "rate"],
  ColonistMoodOffset: ["Flat amount added to or subtracted from colonist mood. 0 leaves it unchanged.", "points"],
  AllowAllMods: ["Skip server checks for the mod list, load order and settings."],
  EnforceSettings: ["Require players' mod settings to match the server configuration when bypass is off."],
};

const actionHelp = {
  Raid: "Let standard players initiate raids against other players.",
  Trade: "Let standard players transfer items through player trading.",
  Caravan: "Let standard players use RimWorld Together's caravan interactions.",
  Aid: "Let standard players send aid to another player.",
  Event: "Let standard players send events to another player.",
  Market: "Let standard players list and buy items on the shared marketplace.",
  Guild: "Let standard players use guild actions.",
  Site: "Let standard players use shared site actions.",
  Road: "Let standard players perform road-building actions. Existing roads keep their travel multipliers.",
  River: "Let standard players use the server's river actions.",
  Pollution: "Let standard players synchronize world-tile pollution changes.",
  Scenario: "Let players use the scenario editor and select custom starting scenarios.",
};

export function configHelp(file, key) {
  if (file.startsWith("Assets/Events/")) {
    return {
      Name: ["Display name in the event list."],
      Cost: ["Amount paid by the player who sends this event.", "Silver"],
      IsEnabled: ["Make this event available in the player event list."],
    }[key];
  }
  if (key === "IsEnabled") return [actionHelp[file.split("/").pop().replace(".json", "")]];
  if (key === "IsEnforced") {
    return [file.endsWith("StorytellerConfig.json")
      ? "Require players to use the storyteller selected by the in-game admin."
      : "Require new colonies on the existing world to use the scenario selected by the in-game admin."];
  }
  if (key.startsWith("RoadValues.")) {
    if (key.endsWith("Cost")) return ["Amount paid from the caravan for one road segment.", "Silver"];
    if (key.endsWith("Multiplier")) return ["Multiply caravan movement difficulty on this road. 1 is unchanged.", "×"];
    return ["Allow players to build this type of road."];
  }
  return fieldHelp[key] || [];
}

export function fieldDependency(key) {
  return {
    MessageOfTheDay: ["EnableMoTD", true],
    IntervalHours: ["AutomaticBackups", true],
    Amount: ["AutomaticDeletion", true],
    Cooldown: ["IsEnabled", true],
    EnforceSettings: ["AllowAllMods", false],
  }[key];
}
