import sqlite3 
import sqlalchemy as db 

# CRIA TABELAS 

def cria_tbl_followers():
    """DROP AND CREATE TABLE followers"""

    conn = sqlite3.connect('instagram.db') #TODO Levar estes comandos para fora da função
    cur = conn.cursor() #TODO Levar estes comandos para fora da função

    cur.execute('DROP TABLE IF EXISTS followers')

    cur.execute('''
    CREATE TABLE followers (pk INTEGER PRIMARY KEY, username TEXT, full_name TEXT, data_entrada TEXT, data_saida TEXT)''') 

    cur.close() 

    print('followers table created')

def cria_tbl_new_followers():
    """DROP AND CREATE TABLE new_followers"""
    
    conn = sqlite3.connect('instagram.db')
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS new_followers')

    cur.execute('''
    CREATE TABLE new_followers (pk INTEGER PRIMARY KEY, username TEXT, follow_time TEXT, welcome TEXT)''') 

    cur.close() 

    print('new_followers table created')

def cria_tbl_followings():
    """DROP AND CREATE TABLE followings"""
    
    conn = sqlite3.connect('instagram.db')
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS followings')

    cur.execute('''
    CREATE TABLE followings (pk INTEGER PRIMARY KEY, username TEXT, full_name TEXT)''') 

    cur.close() 

    print('followings table created')

def cria_tbl_posts():
    """DROP AND CREATE TABLE posts"""

    conn = sqlite3.connect('instagram.db')
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS posts')

    cur.execute('''
    CREATE TABLE posts (post_id TEXT PRIMARY KEY, media_type INTEGER, criado_em_post TEXT, dia_semana_post INTEGER, comment_count INTEGER, like_count INTEGER, caption_text TEXT, hashtags TEXT, view_count INTEGER, repost TEXT)''') 

    cur.close() 

    print('table posts created') 

def cria_tbl_likes():
    """DROP AND CREATE TABLE likes"""
    conn = sqlite3.connect('instagram.db')
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS likes')

    cur.execute('''
    CREATE TABLE likes (post_pk INTEGER, follower_pk INTEGER, PRIMARY KEY (post_pk, follower_pk))''') 

    cur.close() 

    print('Table likes created')

def cria_tbl_comments():
    """DROP AND CREATE TABLE comments"""
    conn = sqlite3.connect('instagram.db')
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS comments')

    cur.execute('''
    CREATE TABLE comments (post_pk TEXT, comment_pk INTEGER PRIMARY KEY, 'text' TEXT, 
    follower_pk INTEGER,is_private BOOL, created_at TEXT, content_type TEXT, 
	status TEXT, has_liked_comment BOOL, like_count INTEGER)''') 

    cur.close() 

    print('Table comments created')

def cria_tbl_convites_instagrow():
    """DROP AND CREATE TABLE convites_instagrow"""
    conn = sqlite3.connect('instagram.db')
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS convites_instagrow')

    cur.execute('''
    CREATE TABLE convites_instagrow (username TEXT PRIMARY KEY)''') 

    cur.close() 

    print('Table convites_instagrow created')


# ATUALIZA TABELAS

def insere_followers(df): 
    """INSERT/UPDATE RECORDS IN TABLE followers"""

    engine = db.create_engine('sqlite:///instagram.db', echo=False)

    with engine.begin() as connection:
        df.to_sql('followers', con=engine, if_exists='replace', index = False) 
        #https://datatofish.com/pandas-dataframe-to-sql/

 
def atualiza_followers(df, data_atualizacao): 
    """ INSERT/UPDATE RECORDS IN TABLE followers_temp """

    # importa df de followers para a tabela followers_temp
    engine = db.create_engine('sqlite:///instagram.db', echo=False)

    with engine.begin() as connection:
        df.to_sql('followers_temp', con=engine, if_exists='replace', index = False) 
        #https://datatofish.com/pandas-dataframe-to-sql/

    
    conn = sqlite3.connect('instagram.db')

    #update the data_saida field in the followers table that are not in the followers_temp table
    atualiza_saida = """UPDATE followers SET data_saida = '%s' 
                        WHERE pk NOT IN (SELECT pk FROM followers_temp) AND data_saida IS NULL"""
    
    cur = conn.cursor()    
    cur.execute(atualiza_saida %(data_atualizacao)) 

    # insert new followers from followers_temp table into the followers with data_entrada of the day
    atualiza_entrada = """INSERT INTO followers (pk, username, full_name, data_entrada) 
                         SELECT pk, username, full_name, '%s' AS data_entrada FROM followers_temp ft 
                         WHERE pk NOT IN (SELECT pk FROM followers WHERE data_saida IS NULL)"""

    cur = conn.cursor()    
    cur.execute(atualiza_entrada %(data_atualizacao)) 

    # update common records in the 2 tables that have different username or full_name in temp
    #https://stackoverflow.com/questions/19270259/update-with-join-in-sqlite
    atualiza_dados_basicos = """UPDATE followers 
                                SET 
	                                username = (SELECT username FROM followers_temp WHERE pk = followers.pk),  
	                                full_name = (SELECT full_name FROM followers_temp WHERE pk = followers.pk),
                                    data_update = '%s' 
                                where 
                                    EXISTS (SELECT pk FROM followers_temp WHERE pk = followers.pk)
                                    AND data_saida IS NULL"""

    cur = conn.cursor() 
    cur.execute(atualiza_dados_basicos %(data_atualizacao)) 
    
    conn.commit()

    conn.close() 
    
def insere_new_followers(df): 
    """ INSERT/UPDATE IN TABLE new_followers """ 

    dict_temp = dict(df.T)

    insere_registro = "INSERT OR IGNORE INTO new_followers ('pk', 'username', 'follow_time') VALUES (%d, '%s', '%s')" 

    conn = sqlite3.connect('instagram.db')
    cur = conn.cursor()

    for i in range(len(dict_temp)):
        temp = cur.execute(insere_registro %(dict_temp[i].user_id, dict_temp[i].username, dict_temp[i].follow_time)) 

    conn.commit()

    conn.close() 

def insere_followings(df): 
    """ INSERT/UPDATE IN TABLE followings """

    engine = db.create_engine('sqlite:///instagram.db', echo=False)
    #engine = db.create_engine('sqlite:///instagram.db') # sqlalchemy

    with engine.begin() as connection:
        df.to_sql('followings', con=engine, if_exists='replace', index = False) 
        #append -> replace
        #https://datatofish.com/pandas-dataframe-to-sql/


def insere_posts(df):
    """ INSERT / UPDATE IN TABLE posts"""
    
    dict_temp = dict(df.T)

    insere_registro = "INSERT OR REPLACE INTO posts ('post_pk', 'media_type', 'criado_em_post', 'dia_semana_post', 'comment_count', 'like_count', 'caption_text', 'hashtags', 'view_count', 'repost') \
    VALUES ('%s', %d, '%s', %d, %d, %d, '%s', '%s', %d, '%s')"


    conn = sqlite3.connect('instagram.db')
    cur = conn.cursor()

    for i in range(len(dict_temp)):
        temp = cur.execute(insere_registro %(dict_temp[i].post_id, dict_temp[i].media_type, dict_temp[i].criado_em_post, dict_temp[i].dia_semana_post, dict_temp[i].comment_count, dict_temp[i].like_count, dict_temp[i].caption_text, dict_temp[i].hashtags, dict_temp[i].view_count, dict_temp[i].repost)) 

    conn.commit()

    conn.close() 

def insere_likes(df):
    """INSERT/UPDATE IN TABLE likes"""

    dict_temp = dict(df.T)

    insere_registro = "INSERT OR REPLACE INTO likes ('post_pk', 'follower_pk') VALUES ('%s', %d)"

    conn = sqlite3.connect('instagram.db')
    cur = conn.cursor()

    for i in range(len(dict_temp)):
        temp = cur.execute(insere_registro %(dict_temp[i].post_pk, dict_temp[i].follower_pk)) 

    conn.commit()

    conn.close() 

def insere_comments(df): 
    """INSERT/UPDATE IN TABLE comments"""

    dict_temp = dict(df.T)

    insere_registro = "INSERT OR REPLACE INTO comments ('post_pk', 'comment_pk', 'text', 'follower_pk', \
        'is_private', 'created_at', 'content_type', 'status', 'has_liked_comment', 'like_count') \
        VALUES ('%s', %d, '%s', %d, '%s', '%s', '%s', '%s', '%s', %d)"

    conn = sqlite3.connect('instagram.db')
    cur = conn.cursor()

    for i in range(len(dict_temp)):
        temp = cur.execute(insere_registro %(dict_temp[i].post_pk, dict_temp[i].comment_pk, dict_temp[i].text, \
        dict_temp[i].follower_pk, dict_temp[i].is_private, dict_temp[i].created_at, dict_temp[i].content_type, \
        dict_temp[i].status, dict_temp[i].has_liked_comment, dict_temp[i].like_count)) 

    conn.commit()

    conn.close() 

