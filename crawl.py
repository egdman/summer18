import sys
import os
import re
import shutil
import asyncio
import aiohttp
from time import clock
from itertools import chain
from urllib import request, parse
from html.parser import HTMLParser
from argparse import ArgumentParser
from asyncio import Queue


def canonize(url):
  return re.sub(r'/+$', '', url.strip()) + '/'

def defrag(url):
  return parse.urlunsplit(parse.urlsplit(url)[:3] + ('',''))

def makeFilename(url):
  url = canonize(url)[:-1]
  return re.sub(r'/', '..', re.sub(r'^(\w*?)://', '', url))


class MyHTMLParser(HTMLParser):
  def __init__(self):
    super(MyHTMLParser, self).__init__()
    self.foundLinks = []


  def handle_starttag(self, _, attrs):
    self.foundLinks.extend(
      (value.strip() for name, value in attrs if value and name in ("href", "src")))


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
    with open(filename, 'wb'): pass
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


async def download_noexcept(url, session, filename):
  try:
    page = await session.get(url)

    try:
      return await downloadAsync(page, filename)
    finally:
      page.close()

  except Exception as ex:
    print("while downloading this link: '{}',".format(url))
    print("this happened: {} : {}".format(type(ex), ex))

  return ""


async def fetchAsync(url, root, eventLoop, filename):
  # dl to temp file
  tempFilename = filename + ".__"
  pageText = ""
  async with aiohttp.ClientSession(loop = eventLoop) as session:
    pageText = await download_noexcept(url, session, tempFilename)

  # parse text to find links
  parser = MyHTMLParser()
  parser.feed(pageText)
  absLinks = (defrag(parse.urljoin(url, link)) for link in parser.foundLinks)
  absLinks = set(link for link in absLinks if os.path.commonprefix((link, root)) == root)

  # write links to disk
  linkFilename = tempFilename + ".links"
  with open(linkFilename, "w") as stream:
    stream.write('\n'.join(absLinks))
  
  # rename file
  shutil.move(tempFilename, filename)
  return url, absLinks


def filenames(inputPath):
  for _, _, filenames in os.walk(inputPath):
    for filename in filenames:
      yield filename


class Spider(object):
  def __init__(self, rootUrl, rootDir, _):
    self.root = rootUrl
    self.rootDir = rootDir
    # self.cache = cacheFilename

    self.queue = Queue()
    self.queue.put_nowait(rootUrl)
    self.pending = set()

    # read downloaded urls
    # self.down = set(filenames(rootDir))

    # read pending urls
    # try:
    #   with open(self.cache, 'r') as stream:
    #     for link in stream.read().strip().split():
    #       self.queue.put_nowait(link)
    # except OSError:
    #   pass


  # def writeCache(self):
  #   started = clock()
  #   foundLinks = set()
  #   while not self.queue.empty():
  #     foundLinks.add(self.queue.get_nowait())

  #   for link in foundLinks:
  #     self.queue.put_nowait(link)

  #   foundLinks = foundLinks.union(self.pending)

  #   # print("down:   {} links".format(len(self.down)))
  #   with open(self.cache, 'w') as stream:
  #     stream.write('\n'.join(foundLinks))

  #   print("cached {} in {:.2f} ms".format(len(foundLinks), 1000*(clock() - started)))
  #   return len(foundLinks)


  # async def runCaching(self):
  #   while True:
  #     await asyncio.sleep(2)
  #     self.writeCache()

  async def monitor(self):
    while True:
      await asyncio.sleep(2)
      print("pending {} links".format(len(self.pending)))
  

  async def run(self, eventLoop):
    monitorTask = asyncio.ensure_future(self.monitor())

    def whenDownloaded(task):
      thisLink, nextLinks = task.result()

      self.pending.remove(thisLink)
      newLinks = list(link for link in nextLinks if not \
        os.path.exists(os.path.join(self.rootDir, makeFilename(link))))

      # print(str(len(nextLinks)) + " : " + str(len(newLinks)))
      for link in newLinks:
        self.queue.put_nowait(link)

    while True:

      if len(self.pending) >= 100: # too many tasks
        await asyncio.sleep(.01)

      elif not self.queue.empty():
        link = defrag(await self.queue.get())

        if link not in self.pending:
          self.pending.add(link)
          filename = os.path.join(self.rootDir, makeFilename(link))
          task = asyncio.ensure_future(fetchAsync(link, self.root, eventLoop, filename))
          task.add_done_callback(whenDownloaded)


      elif len(self.pending) == 0:
        break

      else:
        await asyncio.sleep(.01)

    # self.writeCache()
    monitorTask.cancel()


def main():
  parser = ArgumentParser()
  parser.add_argument("url", type=str, help="URL to explore")

  args = parser.parse_args()
  rootUrl = canonize(args.url)  
  downloadTo = makeFilename(rootUrl)
  if os.path.exists(downloadTo):
    pass
  else:
    os.mkdir(downloadTo)

  try:
    from appdirs import user_cache_dir
    cacheDir = user_cache_dir("summer18")
    if not os.path.exists(cacheDir):
      os.makedirs(cacheDir)
    cacheTo = os.path.join(cacheDir, downloadTo + ".cache")
  except (ImportError, OSError):
    cacheTo = os.path.join("./", downloadTo + ".cache")

  print("downloading to: " + downloadTo)
  print("    caching to: " + cacheTo)


  def handler(loop, context):
    pass

  started = clock()
  spider = Spider(rootUrl, downloadTo, cacheTo)
  loop = asyncio.get_event_loop()
  loop.set_exception_handler(handler)
  try:
    loop.run_until_complete(spider.run(loop))
    print("done")
  except KeyboardInterrupt as ex:
    loop.call_exception_handler({"exception": ex})
    print("interrupted")

  print("{:.1f} seconds".format(clock() - started))


if __name__ == '__main__': main()
