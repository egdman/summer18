import os
from urllib import request, parse
from html.parser import HTMLParser
import asyncio
from asyncio import Queue
import aiohttp

import re
def noSlash(url):
  return re.sub(r'/', '..', re.sub(r'^(\w*?)://', '', url))


def defrag(link):
  link, _ = parse.urldefrag(link)
  return link


class MyHTMLParser(HTMLParser):
  def __init__(self, root):
    super(MyHTMLParser, self).__init__()
    self.root = parse.urlsplit(root)
    self.foundLinks = []


  def toAbsolute(self, link):
    if link.netloc == "" and not link.path.startswith("/"):
      return (self.root.scheme, self.root.netloc, os.path.join(self.root.path, link.path)) + link[3:]

    if (link.netloc == "" and link.path.startswith("/")) or link.netloc == self.root.netloc:
      if os.path.commonprefix((self.root.path, link.path)) == self.root.path:
        return (self.root.scheme, self.root.netloc, link.path) + link[3:]
      else:
        return None
    # if link.netloc == self.root.netloc:
    #   if os.path.commonprefix(self.root.path, link.path) == self.root.path:
    #     return (self.root.scheme, self.root.netloc, link.path) + link[3:]
    #   else:
    #     return None


  def handle_starttag(self, tag, attrs):
    hrefs = (value for name, value in attrs if name == "href")
    link = next(hrefs, None)
    if link:
      link = self.toAbsolute(parse.urlsplit(defrag(link)))
      if link:
        self.foundLinks.append(parse.urlunsplit(link))


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


# def fetch(url):
#   parser = MyHTMLParser(url)

#   pageContent = ""
#   with request.urlopen(url) as page:
#     # print(page.url)
#     # print(page.getcode())
#     # print(page.info())

#     header = page.info()
#     try:
#       contentSize = int(header["Content-Length"])
#     except Exception:
#       contentSize = 0

#     print("size: {}".format(contentSize))

#     firstChunk = page.read(1024)

#     if canDecode(firstChunk, "utf-8"):
#       # print("good utf-8")
#       # print(firstChunk.decode("utf-8"))
#       pageContent = firstChunk + page.read()
#       pageContent = doDecode(pageContent, "utf-8")
#     else:
#       # print("not good utf-8")
#       pass

#   parser.feed(pageContent)
#   # for lk in parser.foundLinks: print(lk)
#   return pageContent, parser.foundLinks


async def _parseStream(stream):
  header = stream.headers
  try:
    contentSize = int(header["Content-Length"])
  except Exception:
    contentSize = 0

  # print("size: {}".format(contentSize))

  firstChunk = await stream.content.read(1024)

  if canDecode(firstChunk, "utf-8"):
    # print("good utf-8")
    # print(firstChunk.decode("utf-8"))
    content = firstChunk + await stream.content.read()
    return doDecode(content, "utf-8")
  else:
    # print("not good utf-8")
    return ""


# async def fetchAsync(url, loop):
#   async with aiohttp.ClientSession(loop = loop) as session:
#     async with session.get(url) as page:
#       try:
#         pageContent = await _parseStream(page)
#       finally:
#         page.close()

#   parser = MyHTMLParser(url)
#   parser.feed(pageContent)
#   # print("found {} links".format(len(parser.foundLinks)))
#   # for lk in parser.foundLinks: print(lk)
#   return pageContent, parser.foundLinks


async def _safeDownloadContent(url, session):
  try:
    page = await session.get(url)

    try:
      return await _parseStream(page)
    finally:
      page.close()

  except Exception as ex:
    print(type(ex), ex)

  return ""


async def fetchAsync(url, root, eventLoop):
  print(url)
  pageContent = ""
  async with aiohttp.ClientSession(loop = eventLoop) as session:
    pageContent = await _safeDownloadContent(url, session)

  parser = MyHTMLParser(root)
  parser.feed(pageContent)
  # print("found {} links".format(len(parser.foundLinks)))
  # for lk in parser.foundLinks: print(lk)
  # def makeAbsolute(links):
  #   for lk in links:
  #     parsed = parse.urlsplit(lk)
  #     if parsed.netloc == "":
  #       yield parse.urlunsplit((scheme, netloc, parsed.path, parsed.query, parsed.fragment))
  #     else:
  #       yield lk

  return url, parser.foundLinks



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

from appdirs import user_cache_dir
from argparse import ArgumentParser

parser = ArgumentParser()
parser.add_argument("url", type=str, help="URL to explore")


def filenames(inputPath):
  for _, _, filenames in os.walk(inputPath):
    for filename in filenames:
      yield filename


class Spider(object):
  def __init__(self, url, rootDir):
    self.root = url

    # read downloaded urls
    self.down = set(filenames(rootDir))

    # read pending urls
    self.cache = os.path.join(user_cache_dir("summer18"), "pending.links")
    try:
      with open(self.cache, 'r') as stream:
        startUrls = set(stream.read().decode("utf-8").strip().split())
    except (OSError, UnicodeDecodeError):
      startUrls = set([url])

    self.pending = set()
    self.dir = rootDir
    self.queue = Queue()
    for lk in startUrls:
      self.queue.put_nowait(lk)


  async def doCaching(self):
    while True:
      await asyncio.sleep(5)
      newLinks = []
      while not self.queue.empty():
        newLinks.append(self.queue.get_nowait())

      print("in queue   : " + str(len(newLinks)) + " links")
      print("in pending : " + str(len(self.pending)) + " links")
      for link in newLinks:
        self.queue.put_nowait(link)


  async def run(self, eventLoop):
    asyncio.ensure_future(self.doCaching())

    def whenDownloaded(task):
      thisLink, nextLinks = task.result()
      self.pending.remove(thisLink)
      self.down.add(thisLink)
      newLinks = (link for link in nextLinks if link not in self.down)
      for link in newLinks:
        self.queue.put_nowait(link)


    while len(self.pending) or not self.queue.empty():

      if len(self.pending) >= 100: # too many tasks
        await asyncio.sleep(.01)
        continue

      if len(self.pending) == 0 and self.queue.empty():
        break
      link = await self.queue.get()

      if link not in self.pending and link not in self.down:
        self.pending.add(link)
        task = asyncio.ensure_future(fetchAsync(link, self.root, eventLoop))
        task.add_done_callback(whenDownloaded)

        # print(self.n)
        # await asyncio.sleep(.02)

    print("done")


def main():
  args = parser.parse_args()

  downloadTo = noSlash(args.url)
  print(downloadTo)

  if os.path.exists(downloadTo):
    pass
  else:
    os.mkdir(downloadTo)


  # read downloaded urls
  downloadedLinks = set(filenames(downloadTo))

  # read pending urls
  cacheFile = os.path.join(user_cache_dir("summer18"), "pending.links")
  try:
    with open(cacheFile, 'r') as stream:
      pendingLinks = set(stream.read().decode("utf-8").strip().split())
  except (OSError, UnicodeDecodeError):
    pendingLinks = set([downloadTo])

  # TODO add exception handling like KeyboardInterrupt
  spider = Spider(args.url, downloadTo)
  loop = asyncio.get_event_loop()
  future = asyncio.ensure_future(spider.run(loop))
  loop.run_until_complete(future)


if __name__ == '__main__': main()
