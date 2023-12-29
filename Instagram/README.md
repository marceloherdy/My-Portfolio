# Instagram Integration in Python
This Python script is designed to automate various tasks related to Instagram page maintenance. The script includes functionalities such as unfollowing followers without interaction and sending a welcome message to new followers. The data needed for these operations, including followers, followings, posts, likes, and comments, are extracted from Instagram and stored in an SQLite database.

## Getting Started
Prerequisites
Make sure you have the required Python libraries installed: pandas instagrapi sqlalchemy instabot

## Setting up your Instagram credentials and other parameters:
Open the script and modify the following variables:
* conta = '12345678901'  # Instagram account
* usr = 'your_user'  # Instagram User
* psw = 'your_password'  # Instagram Password
* nossos_usernames = ['profile1', '...', 'profilen']  # List of your users who follow the Instagram profile
* nao_excluir = ['profile1', '...', 'profilen']  # List of users that you will not unfollow
* path_raiz = os.getcwd()  # Define the root path

## Notes
* Some functionalities include options to import data from CSV files instead of extracting it again from Instagram. Uncomment and execute those cells as needed.
* Techniques are implemented to avoid Instagram blocks, such as waiting periods and occasional breaks during mass unfollowing.
* Feel free to explore and customize the script based on your specific requirements. If you encounter any issues or have suggestions for improvements, please open an issue or pull request on the GitHub repository.

## Functionality Overview
1. Imports and Setups: General imports for working with data, time, and Instagram API, SQLite databases, and custom functions.
2. Creating Required Tables in SQLite: Uncomment and run this cell only when you want to recreate the tables. Note: Existing tables will be dropped!
3. Defining Variables: Setting up variables such as Instagram account details, usernames, and periods.
4. Log in to Instagram: Logging into Instagram using instagrapi with Multi-Factor Authentication (MFA) support.
5. Extracting Followings: Extracting followings from the Instagram account.
6. Import Followings from CSV File: Uncomment and execute this cell only when you prefer to import a previously generated followings file instead of extracting it again from Instagram.
7. Extracting Followers: Extracting followers and updating the SQLite table with follower information.
8. Import Followers from CSV File: Uncomment and execute this cell only when you prefer to import previously generated followers files instead of extracting them again from Instagram.
9. Send Welcome Message: Creating a list of new followers and sending welcome messages using the instabot library.
10. Extracting Posts: Extracting posts from the Instagram account and updating the SQLite table with post information.
11. Import Posts from CSV File: Uncomment and execute this cell only when you prefer to import a previously generated posts file instead of extracting it again from Instagram.
12. Export Posts: Filtering and exporting posts created after a cutoff date.
13. Export Comments: Extracting and exporting comments on the posts.
14. Import Comments from CSV File: Uncomment and execute this cell only when you prefer to import a previously generated comments file instead of extracting it again from Instagram.
15. Extracting Likes: Extracting and exporting likes on the posts.
16. Import Likes from CSV File: Uncomment and execute this cell only when you prefer to import a previously generated likes file instead of extracting it again from Instagram.
17. Finding Followed Without Interaction: Identifying users followed without interaction with the page and exporting the results.
18. Unfollow User: Unfollowing users with techniques to avoid Instagram blocks.
