import os
import re
import asyncio
import aiohttp
from time import clock
from itertools import chain
from urllib import request, parse
from html.parser import HTMLParser
from appdirs import user_cache_dir
from argparse import ArgumentParser
from asyncio import Queue


def canonize(url):
  return re.sub(r'/+$', '', url.strip()) + '/'

def defrag(link):
  link, _ = parse.urldefrag(link)
  return link

def makeFilename(url):
  url = canonize(url)[:-1]
  return re.sub(r'/', '..', re.sub(r'^(\w*?)://', '', url))


class MyHTMLParser(HTMLParser):
  def __init__(self):
    super(MyHTMLParser, self).__init__()
    self.foundLinks = []


  def handle_starttag(self, _, attrs):
    self.foundLinks.extend(
      (value for name, value in attrs if name in ("href", "src")))


def canDecode(data, enc):
  def _canDecode(chunk):
    try:
      chunk.decode(enc)
      return True
    except UnicodeDecodeError:
      return False

  sz = len(data)
  for chunkSz in range(sz, sz - 5, -1):
    if _canDecode(data[:chunkSz]): return True
  return False


def doDecode(data, enc):
  try:
    return data.decode(enc)
  except UnicodeDecodeError:
    return ""


async def downloadAsync(istream, filename):
  chunkSz = 1024

  firstChunk = await istream.content.read(chunkSz)
  if not canDecode(firstChunk, "utf-8"):
    return ""

  fullContent = bytes()
  with open(filename, 'wb') as ostream:
    ostream.write(firstChunk)
    fullContent += firstChunk
    while True:
      chunk = await istream.content.read(chunkSz)
      if not chunk:
        break
      ostream.write(chunk)
      fullContent += chunk

  return doDecode(fullContent, "utf-8")


async def safeDownloadContent(url, session, filename):
  try:
    page = await session.get(url)

    try:
      return await downloadAsync(page, filename)
    finally:
      page.close()

  except Exception as ex:
    print(type(ex), ex, url)

  return ""


async def fetchAsync(url, root, domain, eventLoop, filename):
  # print(url)
  pageContent = ""
  async with aiohttp.ClientSession(loop = eventLoop) as session:
    pageContent = await safeDownloadContent(url, session, filename)

  parser = MyHTMLParser()
  parser.feed(pageContent)

  absLinks = (defrag(parse.urljoin((domain if link.startswith('/') else url), link)) \
    for link in parser.foundLinks)
  return url, set(link for link in absLinks if os.path.commonprefix((link, root)) == root)


urls = [
"https://docs.python.org/3/library/urllib.request.html#module-urllib.response",
"https://github.com/aio-libs/aiohttp/blob/master/aiohttp/streams.py",
"https://download.qt.io/official_releases/qt/5.11/5.11.0/qt-opensource-windows-x86-pdb-files-uwp-5.11.0.7z",
"https://bpy.wikipedia.org/wiki/%E0%A6%9C%E0%A6%BE%E0%A6%AA%E0%A6%BE%E0%A6%A8",
"https://stackoverflow.com/questions/9110593/asynchronous-requests-with-python-requests",
"https://www.youtube.com/watch?v=WiQYjPdq_qI",
"https://www.youtube.com/watch?v=FD_-b06JJtE",
"https://www.jytrhgf.com/stuff",
]



parser = ArgumentParser()
parser.add_argument("url", type=str, help="URL to explore")


def filenames(inputPath):
  for _, _, filenames in os.walk(inputPath):
    for filename in filenames:
      yield filename


class Spider(object):
  def __init__(self, rootUrl, rootDir):
    self.root = rootUrl
    self.domain = parse.urlunsplit(parse.urlsplit(rootUrl)[:2] + ('','',''))
    self.rootDir = rootDir

    # read downloaded urls
    self.down = set(filenames(rootDir))
    self.pending = set()

    # read pending urls
    cacheDir = user_cache_dir("summer18")
    try:
      if not os.path.exists(cacheDir):
        os.makedirs(cacheDir)
      self.cache = os.path.join(cacheDir, rootDir)
    except OSError:
      self.cache = so.path.join("./", rootDir)

    print("cache to: " + self.cache)

    self.queue = Queue()
    self.queue.put_nowait(rootUrl)
    try:
      with open(self.cache, 'r') as stream:
        for link in stream.read().strip().split():
          self.queue.put_nowait(link)
    except (OSError, UnicodeDecodeError):
      pass


  async def doCaching(self):
    while True:
      await asyncio.sleep(2)

      started = clock()
      foundLinks = set()
      while not self.queue.empty():
        foundLinks.add(self.queue.get_nowait())

      for link in foundLinks:
        self.queue.put_nowait(link)

      foundLinks = foundLinks.union(self.pending)

      print("down:   {} links".format(len(self.down)))
      with open(self.cache, 'w') as stream:
        for link in foundLinks: stream.write(link + '\n')

      print("cached {} in {:.2f} ms".format(len(foundLinks), 1000*(clock() - started)))



  async def run(self, eventLoop):
    asyncio.ensure_future(self.doCaching())

    def whenDownloaded(task):
      thisLink, nextLinks = task.result()
      self.down.add(makeFilename(thisLink))
      self.pending.remove(thisLink)
      newLinks = (link for link in nextLinks if makeFilename(link) not in self.down)
      for link in newLinks:
        self.queue.put_nowait(link)


    while len(self.pending) or not self.queue.empty():

      if len(self.pending) >= 100: # too many tasks
        await asyncio.sleep(.01)
        continue

      if len(self.pending) == 0 and self.queue.empty():
        break
      link = await self.queue.get()

      if link not in self.pending:
        self.pending.add(link)
        filename = os.path.join(self.rootDir, makeFilename(link))
        task = asyncio.ensure_future(fetchAsync(link, self.root, self.domain, eventLoop, filename))
        task.add_done_callback(whenDownloaded)



def main():
  args = parser.parse_args()
  rootUrl = canonize(args.url)  
  downloadTo = makeFilename(rootUrl)

  print(downloadTo)

  if os.path.exists(downloadTo):
    pass
  else:
    os.mkdir(downloadTo)


  # TODO add exception handling like KeyboardInterrupt
  spider = Spider(rootUrl, downloadTo)
  loop = asyncio.get_event_loop()
  loop.run_until_complete(spider.run(loop))

  print("done")

if __name__ == '__main__': main()
