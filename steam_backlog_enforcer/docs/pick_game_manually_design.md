Add an option to pick a specific game manually (by providing its steam id)
Picking a game should work like this:
1. user invokes script with specific flag for picking a game manually
2. user provides game steam id (in testing use 489830)
3. Script shows what game it believes this id means (in this case it should show The Elder Scrolls V: Skyrim Special Edition)
4. user confirms that this is the game they want to pick and confirm that they will not be able to use the script for up to 2 weeks or until the game is completed (100% achievements)

When user picks a game manually this should override the current pick if it exists
After picking manually backlog enforcer should make a note of that and very aggressively disallow user to do anything else
for a period of 2 weeks or until user completes a given game
Logic should be as follows:
    1. backlog checks if a user picked game manually
        a. if not -> continue as before
    2. if yes check if the game is completed
        a. if yes -> continue as before
    3. if NOT show info that user picked a specific game manually and they have to finish it before using ANY OTHER functionality of backlog enforcer

test the functionality with 489830 (The Elder Scrolls V: Skyrim Special Edition)
as always first write full functionality confirm that it works alone and with the user and only AFTER that write tests and coverage and fix issues
