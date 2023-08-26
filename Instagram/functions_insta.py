from datetime import datetime, timedelta 
import pandas as pd
import os, time, csv, glob 
from random import randint
import re

# importing instagrapi
from instagrapi import Client 
cl = Client()


# INSTAGRAM DATA EXTRACTION FUNCTIONS

def extrai_followers_instagrapi(path_raiz, conta):
    """ EXTRACT FOLLOWERS AND CREATE DATAFRAME df_followers AND EXPORT CSV"""

    print('Starting extraction at', datetime.today()) 

    followers = cl.user_followers(conta)
    
    list_pk = []
    list_username = [] 
    list_full_name = []

    for key in followers.keys():
        registro = list(followers[key])

        list_pk.append(registro[0][1])
        list_username.append(registro[1][1])
        list_full_name.append(registro[2][1])

    lista_de_tuplas = list(zip(list_pk, list_username, list_full_name)) 
    df_followers = pd.DataFrame(lista_de_tuplas, columns=['pk', 'username', 'full_name']) 

    df_followers['full_name'] = df_followers['full_name'].str.replace("'", " ").str.replace('"', " ") 

    data_hora_atual = str(datetime.today()).replace(":","").replace(".","")[:17]    
    df_followers.to_csv(path_raiz + '\\CSVs\\df_followers_' + data_hora_atual + '.csv', encoding='utf-8', sep=';', decimal=',') 
    print('df_followers.csv created')

    print('Followers extraction finished at', datetime.today())

    return df_followers


def extrai_followings_instagrapi(path_raiz, conta):
    """ EXTRACT FOLLOWINGS AND CREATE DATAFRAME df_followings AND EXPORT CSV"""

    print('Starting extraction at', datetime.today()) 

    followings = cl.user_following(conta)
    
    list_pk = []
    list_username = [] 
    list_full_name = []

    for key in followings.keys():
        registro = list(followings[key])

        list_pk.append(registro[0][1])
        list_username.append(registro[1][1])
        list_full_name.append(registro[2][1])

    lista_de_tuplas = list(zip(list_pk, list_username, list_full_name)) 
    df_followings = pd.DataFrame(lista_de_tuplas, columns=['pk', 'username', 'full_name']) 

    df_followings['full_name'] = df_followings['full_name'].str.replace("'", " ").str.replace('"', " ") 

    data_hora_atual = str(datetime.today()).replace(":","").replace(".","")[:17]    
    df_followings.to_csv(path_raiz + '\\CSVs\\df_followings_' + data_hora_atual + '.csv', encoding='utf-8', sep=';', decimal=',') 
    print('df_followings.csv created')

    print('Followers extraction finished at', datetime.today())

    return df_followings


def extrai_posts_instagrapi(path_raiz, conta):
    """ EXTRACT PROFILE POSTS AND CREATE DATAFRAME df_my_posts AND EXPORT CSV"""

    print('Function extrai_posts started at', datetime.today())

    my_posts = cl.user_medias(conta)

    data_hora_atual = str(datetime.today()).replace(":","").replace(".","")[:17]    
    file = open(path_raiz + '\\CSVs\\my_posts_' + data_hora_atual + '.csv', 'w+', newline ='', encoding='utf-8')
    # writing the data into the file
    with file:    
        write = csv.writer(file)
        write.writerows(my_posts)
    print('list my_posts.csv created')

    list_id = []
    list_taken_at = []
    list_media_type = [] 
    list_comment_count = []
    list_like_count = []
    list_caption_text = []
    list_hashtags = []
    list_view_count = []
    list_repost = []

    for post in range(len(my_posts)):
        hashtags = ''
        repost = ''
        registro = list(my_posts[post])
        
        list_id.append(registro[1][1])
        list_taken_at.append(registro[3][1])
        list_media_type.append(registro[4][1]) 
        list_comment_count.append(registro[9][1])
        list_like_count.append(registro[10][1]) 
        list_view_count.append(registro[16][1]) 
        
        chunks = re.split('\\n ?\.+ ?\\n',registro[12][1]) 
        
        if chunks == []:
            list_caption_text.append('') 
            list_hashtags.append('')
            list_repost.append('')
        else:
            list_caption_text.append(chunks[0]) 
            for i in range(1, len(chunks)):
                if chunks[i].lower().find('#repost') > -1:
                    repost = str(chunks[i].replace('.','').replace(',','').replace('\n','').replace('#Repost ','')).strip()
                    
                if chunks[i].find('#') > -1 and chunks[i].lower().find('#repost') == -1:
                    hashtags = str(chunks[i].replace('.','').replace(',','').replace('\n','')).strip()
                
        list_hashtags.append(hashtags)
        list_repost.append(repost)
        
    lista_de_tuplas = list(zip(list_id, list_taken_at, list_media_type, list_comment_count, list_like_count, list_caption_text, list_hashtags, list_view_count, list_repost)) 
    df_my_posts = pd.DataFrame(lista_de_tuplas, columns=['post_id', 'taken_at_post', 'media_type', 'comment_count', 'like_count', 'caption_text', 'hashtags', 'view_count', 'repost']) 

    df_my_posts['criado_em_post'] = df_my_posts['taken_at_post'].dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)
    df_my_posts['dia_semana_post'] =  df_my_posts['taken_at_post'].dt.weekday 

    df_my_posts.drop(['taken_at_post'], axis=1, inplace = True) 

    data_hora_atual = str(datetime.today()).replace(":","").replace(".","")[:17]
    df_my_posts.to_csv(path_raiz + '\\CSVs\\df_my_posts_' + data_hora_atual + '.csv', encoding='utf-8', sep=';', decimal=',') 
    print('df_my_posts.csv created')

    print('Function extrai_posts finished at', datetime.today())

    return df_my_posts 


def extrai_curtidas_instagrapi(path_raiz, my_posts_temp):
    """ EXTRACT LIKES INFORMATION, CREATE DATAFRAME df_my_likes AND EXPORT CSV""" 
    
    print('Starting extrai_likes_instagrapi at', datetime.today()) 
        
    count = 0
    #espera = randint(1, 2)
    n_posts = len(my_posts_temp)

    print("Estimated extraction time is %.1f minutes" % (len(my_posts_temp) * 2.5 / 60.0))

    data_hora_atual = str(datetime.today()).replace(":","").replace(".","")[:17]   

    list_post_pk = []
    list_follower_pk = []
    list_is_private = []
    list_stories = []

    for post in my_posts_temp: 
        likes_temp = cl.media_likers(post) 

        for like in range(len(likes_temp)):
            registro = list(likes_temp[like]) 
            
            list_post_pk.append(post)
            list_follower_pk.append(registro[0][1])
            list_is_private.append(registro[5][1])
            list_stories.append(registro[6][1])
                    
        time.sleep(1) 
        #time.sleep(espera) 
        count += 1
        if count % 20 == 0:
            print(datetime.today(), '-', count, 'of', n_posts, 'extracted')

    lista_de_tuplas = list(zip(list_post_pk, list_follower_pk, list_is_private, list_stories)) 
    df_my_likes = pd.DataFrame(lista_de_tuplas, columns=['post_pk', 'follower_pk', 'is_private', 'stories']) 

    data_hora_atual = str(datetime.today()).replace(":","").replace(".","")[:17]
    df_my_likes.to_csv(path_raiz + '\\CSVs\\df_my_likes_' + data_hora_atual + '.csv', encoding='utf-8', sep=';', decimal=',') 
    print('df_my_likes.csv created \n')

    print(len(df_my_likes), 'likes extracted')
    df_my_likes.head()
    df_my_likes.tail()

    print('\nFunction extrai_likes_instagrapi finished at', datetime.today())
    
    return df_my_likes 


def extrai_comentarios_instagrapi(path_raiz, my_posts_temp):
    """ EXTRACT THE INFORMATION FROM COMMENTS, CREATE DATAFRAME df_my_comments AND EXPORT CSV"""

    print('Starting extrai_comentarios_instagrapi at', datetime.today()) 
        
    count = 0
    #espera = randint(1, 2)
    n_posts = len(my_posts_temp)

    print("Estimated extraction time is %.1f minutes" % (len(my_posts_temp) * 2.5 / 60.0))

    data_hora_atual = str(datetime.today()).replace(":","").replace(".","")[:17]    

    list_post_pk = []
    list_comment_pk = []
    list_text = []
    list_follower_pk = []
    list_is_private = []
    list_stories = []
    list_create_at = []
    list_content_type = []
    list_status = []
    list_has_liked = []
    list_like_count = [] 

    for post in my_posts_temp: 
        comments_temp = cl.media_comments(post, amount = 0) 

        for comment in range(len(comments_temp)):
            registro = list(comments_temp[comment]) 
            
            list_post_pk.append(post)
            list_comment_pk.append(registro[0][1])
            list_text.append(registro[1][1])
            
            temp = list(registro[2][1])
            list_follower_pk.append(temp[0][1])
            list_is_private.append(temp[5][1])
            list_stories.append(temp[6][1])
            
            list_create_at.append(registro[3][1])
            list_content_type.append(registro[4][1])
            list_status.append(registro[5][1])
            list_has_liked.append(registro[6][1])
            list_like_count.append(registro[7][1]) 
            
        time.sleep(1) 
        #time.sleep(espera) 
        count += 1
        if count % 20 == 0:
            print(datetime.today(), '-', count, 'of', n_posts, 'extracted')

    lista_de_tuplas = list(zip(list_post_pk, list_comment_pk, list_text, list_follower_pk, list_is_private, list_stories, list_create_at, list_content_type, list_status, list_has_liked, list_like_count)) 
    df_my_comments = pd.DataFrame(lista_de_tuplas, columns=['post_pk', 'comment_pk', 'text', 'list_follower_pk', 'list_is_private', 'list_stories', 'create_at', 'content_type', 'status', 'has_liked', 'like_count']) 

    df_my_comments['criado_em'] = df_my_comments['create_at'].dt.tz_convert("America/Sao_Paulo") 
    df_my_comments['dia_semana_post'] =  df_my_comments['create_at'].dt.weekday 

    df_my_comments.drop(['create_at'], axis=1, inplace = True) 

    data_hora_atual = str(datetime.today()).replace(":","").replace(".","")[:17]
    df_my_comments.to_csv(path_raiz + '\\CSVs\\df_my_comments_' + data_hora_atual + '.csv', encoding='utf-8', sep=';', decimal=',') 
    print('df_my_comments.csv created \n')

    
    print(len(df_my_comments), 'comments extracted')
    df_my_comments.head()
    df_my_comments.tail()

    print('\nFunction extrai_comentarios_instagrapi finished at', datetime.today())

    return df_my_comments


# AUXILIARY FUNCTIONS

def aux_login_instagrapi(usr, psw): 
    # Login using bot.
    vc = input('Inform the verification_code: ')

    cl.login(usr,psw,verification_code=vc)

    print('Login performed at', datetime.today()) 

def deixa_de_seguir(user_id):
    return cl.user_unfollow(user_id)
