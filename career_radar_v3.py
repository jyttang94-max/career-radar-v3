  url='https://www.bing.com/search?format=rss&q='+quote(q)
  try:
   root=ET.fromstring(get(url).content)
   for x in root.findall('.//item'):
    title=(x.findtext('title') or '').strip();link=(x.findtext('link') or '').strip()
    if title and link and ROLE.search(title):hits.setdefault(link,title)
  except Exception as e:errors.append({'query':q,'error':str(e)[:120]})
 return hits,errors

def extract(url,title):
 r=get(url)
 if r.content[:4]==b'%PDF':
  import io
  from pypdf import PdfReader
  text=' '.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(r.content)).pages[:10])
 else:
  soup=BeautifulSoup(r.content,'html.parser')
  for node in soup.select('script,style,nav,footer'):node.decompose()
  text=soup.get_text(' ',strip=True)
 text=re.sub(r'\s+',' ',text)[:25000]
 if not ROLE.search(title) or not REGION.search(text):return None
 # Mixed permanent/contract postings are not safe to auto-classify.
 if not PERM.search(title) or TEMP.search(title):return None
 candidates=[]
 for label in re.finditer('접수기간|접수마감|원서접수|지원기간|마감일',text):
  fragment=text[label.start():label.start()+180]
  dates=list(DATE.finditer(fragment))
  if dates:
   m=dates[1] if len(dates)>1 else dates[0]
   try:
    d=datetime(*map(int,m.groups())).date()
    if today<=d<=today+timedelta(days=120):candidates.append(d)
   except ValueError:pass
 if not candidates:return None
 lm=re.search(r'근무지역|근무지|근무장소',text)
 loc=text[lm.end():lm.end()+65].strip(' :：') if lm else None
 if not loc or not REGION.search(loc):return None
 qm=re.search('지원자격|응시자격|자격요건',text)
 qual=text[qm.end():qm.end()+110].strip(' :：') if qm else None
 if not qual or len(qual)<8:return None
 inst=re.split('채용|모집|2026|정규직',title)[0].strip(' []-:|')[:40] or title[:40]
 return dict(institution=inst,employment='정규직 전환형' if '전환' in title else '정규직',location=loc[:55],deadline=min(candidates).isoformat(),job=title[:75],qualification=qual,url=r.url)

def email_html(items):
 esc=lambda x:html.escape(str(x),quote=True)
 cards=[]
 for x in items:
  fields=''.join('<tr><td style="color:#718096;width:78px;vertical-align:top;padding:4px 0">'+label+'</td><td style="padding:4px 0">'+esc(x[key])+'</td></tr>' for label,key in [('근무지역','location'),('접수마감','deadline'),('모집 직무','job'),('지원 자격','qualification')])
  cards.append('<table width="100%" style="border:1px solid #dce3ed;background:#fff;font-size:12px"><tr><td style="padding:15px"><b style="font-size:15px">'+esc(x['institution'])+'</b> <span style="color:#2675bf">NEW</span><p>'+esc(x['employment'])+'</p><table width="100%">'+fields+'</table><p><a href="'+esc(x['url'])+'">원문 보기 →</a></p></td></tr></table>')
 rows=''.join('<tr><td width="50%" valign="top" style="padding:6px">'+cards[i]+'</td><td width="50%" valign="top" style="padding:6px">'+(cards[i+1] if i+1<len(cards) else '')+'</td></tr>' for i in range(0,len(cards),2))
 return '<html><body style="margin:0;background:#f4f6fa;font-family:Arial,sans-serif"><table width="680" align="center" style="max-width:680px;background:white"><tr><td style="background:#163f67;color:white;padding:22px;font-size:22px"><b>CAREER RADAR</b><div style="font-size:12px">'+str(today)+' | 신규 '+str(len(items))+'건</div></td></tr><tr><td><table width="100%">'+rows+'</table></td></tr></table></body></html>'

def send(items):
 user=os.environ['NAVER_MAIL_USER'];password=os.environ['NAVER_MAIL_PASSWORD']
 recipients=[x.strip() for x in os.environ['MAIL_TO'].split(',') if x.strip()]
 with smtplib.SMTP_SSL('smtp.naver.com',465,context=ssl.create_default_context(),timeout=30) as smtp:
  smtp.login(user,password)
  for to in recipients:
   msg=EmailMessage();msg['From']=user;msg['To']=to
   msg['Subject']=f'[Career Radar] 신규 채용공고 {len(items)}건 ({today})'
   msg.set_content('\n'.join(x['url'] for x in items));msg.add_alternative(email_html(items),subtype='html')
   smtp.send_message(msg)

def main():
 try:seen=json.loads(STATE.read_text(encoding='utf-8'))
 except (FileNotFoundError,json.JSONDecodeError):seen={}
 hits,errors=search();jobs=[]
 for url,title in hits.items():
  key=hashlib.sha256(url.encode()).hexdigest()[:24]
  if key in seen:continue
  try:
   job=extract(url,title)
   if job:job['key']=key;jobs.append(job)
  except Exception as e:errors.append({'url':url,'error':str(e)[:120]})
 Path('career_radar_report.json').write_text(json.dumps({'date':str(today),'searched':len(QUERIES),'candidates':len(hits),'jobs':jobs,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
 mode=os.environ.get('RADAR_MODE','dry_run')
 if mode=='dry_run':
  Path('career_radar_preview.html').write_text(email_html(jobs),encoding='utf-8');print('DRY_RUN',len(jobs));return
 if jobs:
  send(jobs)
  for job in jobs:seen[job['key']]={'url':job['url'],'date':str(today)}
  STATE.write_text(json.dumps(seen,ensure_ascii=False,indent=2),encoding='utf-8')
  print('SENT',len(jobs))
 else:print('NO_NEW_JOBS')
if __name__=='__main__':main()
